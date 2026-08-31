import asyncio
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main
from app.db import database
from app.models.code_chunk import CodeChunk
from app.models.repository_file import RepositoryFile
from app.routers import repositories, search
from app.services import github
from app.services.chunking import chunk_source, process_repository_chunks
from app.services.embeddings import SimilarChunk, find_similar_chunks
from app.services.rag import RepositoryAnswer, SourceReference


class HealthEndpointTests(unittest.TestCase):
    def test_root_and_health_endpoints(self) -> None:
        client = TestClient(main.app)
        self.assertEqual(client.get("/").json(), {"message": "CodeAtlas backend is running"})
        self.assertEqual(client.get("/health").json()["status"], "healthy")

    def test_database_health_hides_connection_details(self) -> None:
        class BrokenEngine:
            def connect(self):
                raise RuntimeError("postgres://user:secret@host")

        with patch.object(main, "engine", BrokenEngine()):
            response = TestClient(main.app).get("/db-health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "unhealthy", "database": "unavailable"})

    def test_readiness_returns_service_unavailable_without_database_details(self) -> None:
        class BrokenEngine:
            def connect(self):
                raise RuntimeError("postgres://user:secret@host")

        with patch.object(main, "engine", BrokenEngine()):
            response = TestClient(main.app).get("/readyz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unready", "database": "unavailable"})


class DatabaseServiceTests(unittest.TestCase):
    def test_get_db_closes_session_after_request(self) -> None:
        session = SimpleNamespace(closed=False)
        session.close = lambda: setattr(session, "closed", True)
        with patch.object(database, "SessionLocal", return_value=session):
            dependency = database.get_db()
            self.assertIs(next(dependency), session)
            dependency.close()
        self.assertTrue(session.closed)


class GitHubServiceTests(unittest.TestCase):
    def test_parses_canonical_github_urls_and_rejects_http(self) -> None:
        self.assertEqual(
            github.parse_github_repository_url("https://github.com/openai/codex.git"),
            ("openai", "codex"),
        )
        with self.assertRaises(github.InvalidGitHubUrlError):
            github.parse_github_repository_url("http://github.com/openai/codex")

    def test_get_repository_uses_mocked_github_response(self) -> None:
        response = SimpleNamespace(
            status_code=200,
            headers={},
            is_error=False,
            json=lambda: {
                "owner": {"login": "openai"},
                "name": "codex",
                "html_url": "https://github.com/openai/codex",
                "description": "Example",
                "default_branch": "main",
                "stargazers_count": 5,
                "forks_count": 2,
                "language": "Python",
            },
        )
        with patch.object(github, "_get_api_response", new=AsyncMock(return_value=response)) as request:
            result = asyncio.run(github.get_repository("https://github.com/openai/codex"))
        self.assertEqual(result.owner, "openai")
        self.assertEqual(result.name, "codex")
        self.assertEqual(request.await_count, 1)


class RepositoryProcessingTests(unittest.TestCase):
    def test_chunk_source_preserves_line_addresses(self) -> None:
        chunks = chunk_source("one\ntwo\nthree\n")
        self.assertEqual(len(chunks), 1)
        self.assertEqual((chunks[0].start_line, chunks[0].end_line), (1, 3))

    def test_processing_adds_chunks_for_eligible_files_only(self) -> None:
        source_file = SimpleNamespace(
            id=12,
            path="app/service.py",
            extension=".py",
            language="Python",
            content="def value():\n    return 1\n",
        )
        binary_file = SimpleNamespace(
            id=13,
            path="image.png",
            extension=".png",
            language=None,
            content="not processed",
        )
        added: list[CodeChunk] = []

        class FakeDb:
            def scalars(self, _):
                return SimpleNamespace(all=lambda: [source_file, binary_file])

            def execute(self, _):
                return None

            def add(self, value):
                added.append(value)

        result = process_repository_chunks(FakeDb(), SimpleNamespace(id=3))
        self.assertEqual((result.files_processed, result.chunks_created), (1, 1))
        self.assertEqual((added[0].repository_id, added[0].repository_file_id), (3, 12))


class SimilarityRetrievalTests(unittest.TestCase):
    def test_similarity_retrieval_returns_only_query_rows(self) -> None:
        chunk = CodeChunk(
            id=8,
            repository_id=4,
            repository_file_id=2,
            chunk_index=0,
            content="def target(): pass",
            start_line=1,
            end_line=1,
            token_count=5,
        )

        class FakeDb:
            def execute(self, statement):
                compiled = statement.compile()
                self.assertIn("code_chunks.repository_id", str(compiled))
                return SimpleNamespace(all=lambda: [(chunk, "app/target.py", 0.15)])

            def assertIn(self, expected, actual):
                unittest.TestCase().assertIn(expected, actual)

        matches = find_similar_chunks(
            FakeDb(), 4, "target", 5,
            SimpleNamespace(model="text-embedding-3-small", embed=lambda _: [[0.0] * 1536]),
        )
        self.assertEqual([(match.chunk.id, match.path) for match in matches], [(8, "app/target.py")])


class RepositoryApiReliabilityTests(unittest.TestCase):
    def tearDown(self) -> None:
        main.app.dependency_overrides.clear()

    def test_import_uses_mocked_github_and_processes_chunks(self) -> None:
        db = FakeImportDb()
        github_repository = github.GitHubRepository(
            name="demo", github_url="https://github.com/example/demo", description=None,
            default_branch="main", owner="example", stars=0, forks=0, primary_language="Python",
        )
        tree_file = github.GitHubTreeFile(path="app.py", github_sha="abc", size=20)
        with (
            patch.object(repositories, "get_repository", new=AsyncMock(return_value=github_repository)),
            patch.object(repositories, "get_repository_tree", new=AsyncMock(return_value=[tree_file])),
            patch.object(repositories, "get_text_file_contents", new=AsyncMock(return_value={"app.py": "print('ok')\n"})),
            patch.object(repositories, "process_repository_chunks", return_value=SimpleNamespace(files_processed=1, chunks_created=1)),
        ):
            result = asyncio.run(repositories.import_repository(repositories.RepositoryImportRequest(github_url="https://github.com/example/demo"), db))
        self.assertEqual(result.id, 1)
        self.assertTrue(db.committed)
        self.assertEqual(result.files[0].path, "app.py")

    def test_import_rejects_duplicate_before_external_calls(self) -> None:
        db = FakeImportDb(existing=SimpleNamespace(id=1))
        with patch.object(repositories, "get_repository", new=AsyncMock()) as get_repository:
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(repositories.import_repository(repositories.RepositoryImportRequest(github_url="https://github.com/example/demo"), db))
        self.assertEqual(raised.exception.status_code, 409)
        get_repository.assert_not_awaited()

    def test_rag_endpoint_uses_mocked_embedding_and_llm_services(self) -> None:
        db = SimpleNamespace(get=lambda *_: SimpleNamespace(id=5), scalar=lambda _: 1)
        source = SourceReference(chunk_id=11, path="app/main.py", start_line=4, end_line=12)
        main.app.dependency_overrides[search.get_db] = lambda: db
        with (
            patch.object(search, "get_embedding_provider", return_value=SimpleNamespace(model="text-embedding-3-small")),
            patch.object(search, "find_similar_chunks", return_value=[]),
            patch.object(search, "get_llm_provider", return_value=SimpleNamespace(model="gpt-test")),
            patch.object(search, "answer_question", return_value=RepositoryAnswer(answer="Grounded answer", sources=[source])),
        ):
            response = TestClient(main.app).post("/api/repositories/5/ask", json={"question": "Where is startup?"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sources"][0]["path"], "app/main.py")

    def test_validation_errors_have_consistent_safe_shape(self) -> None:
        response = TestClient(main.app).post("/api/repositories/5/ask", json={"question": ""})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Invalid request.")


class FakeImportDb:
    def __init__(self, existing=None):
        self.existing = existing
        self.scalar_calls = 0
        self.committed = False

    def scalar(self, _):
        self.scalar_calls += 1
        return self.existing if self.scalar_calls == 1 else None

    def add(self, repository):
        repository.id = 1

    def flush(self):
        return None

    def commit(self):
        self.committed = True

    def rollback(self):
        return None

    def refresh(self, _):
        return None
