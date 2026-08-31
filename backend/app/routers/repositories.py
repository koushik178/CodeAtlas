"""Repository import API endpoints."""

from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.code_chunk import CodeChunk
from app.models.repository import Repository
from app.models.repository_file import RepositoryFile
from app.services.chunking import process_repository_chunks
from app.services.github import (
    GitHubApiError,
    GitHubRateLimitError,
    GitHubRepositoryNotFoundError,
    InvalidGitHubUrlError,
    get_repository,
    get_repository_tree,
    get_text_file_contents,
    parse_github_repository_url,
)
from app.services.llm import LLMProviderError, get_llm_provider
from app.services.test_generation import generate_tests, generation_limits, select_file_chunks

router = APIRouter(prefix="/api/repositories", tags=["repositories"])
logger = logging.getLogger(__name__)


class RepositoryImportRequest(BaseModel):
    github_url: str = Field(min_length=1, max_length=2048)

    @field_validator("github_url")
    @classmethod
    def normalize_github_url(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("GitHub repository URL must not be blank.")
        return normalized


class RepositoryResponse(BaseModel):
    id: int
    name: str
    github_url: str
    description: str | None
    default_branch: str | None
    owner: str | None
    stars: int
    forks: int
    primary_language: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ImportedRepositoryResponse(BaseModel):
    """Safe repository metadata needed to reopen a repository in the UI."""

    id: int
    owner: str | None
    name: str
    full_name: str
    github_url: str
    description: str | None
    language: str | None
    default_branch: str | None
    stars: int
    forks: int
    created_at: datetime


class RepositoryFileResponse(BaseModel):
    id: int
    path: str
    filename: str
    extension: str | None
    language: str | None
    size: int | None
    github_sha: str
    has_content: bool


class RepositoryFileTreeResponse(BaseModel):
    repository_id: int
    files: list[RepositoryFileResponse]


class ChunkProcessingResponse(BaseModel):
    repository_id: int
    files_processed: int
    chunks_created: int


class TestGenerationRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)
    focus: str | None = Field(default=None, max_length=300)

    @field_validator("path")
    @classmethod
    def normalize_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Source file path must not be blank.")
        return normalized

    @field_validator("focus")
    @classmethod
    def normalize_focus(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None


class TestGenerationResponse(BaseModel):
    repository_id: int
    source_file_path: str
    language: str
    framework: str
    test_file_path: str
    explanation: str
    test_code: str
    source_chunks: int
    review_notice: str


@router.get("", response_model=list[ImportedRepositoryResponse])
def list_imported_repositories(db: Session = Depends(get_db)) -> list[ImportedRepositoryResponse]:
    """List imported repositories without exposing repository contents or credentials."""
    repositories = db.scalars(
        select(Repository).order_by(Repository.created_at.desc(), Repository.id.desc())
    ).all()
    return [_imported_repository_response(repository) for repository in repositories]


@router.post("/import", response_model=RepositoryResponse, status_code=status.HTTP_201_CREATED)
async def import_repository(payload: RepositoryImportRequest, db: Session = Depends(get_db)) -> Repository:
    """Import GitHub metadata for one public repository, without cloning it."""
    try:
        owner, name = parse_github_repository_url(payload.github_url)
    except InvalidGitHubUrlError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    # Compare the normalized web URL first so URL spelling/trailing slashes do
    # not create duplicates. GitHub's html_url is canonical after retrieval.
    normalized_url = f"https://github.com/{owner}/{name}"
    existing = db.scalar(select(Repository).where(Repository.github_url.ilike(normalized_url)))
    if existing:
        raise HTTPException(status_code=409, detail="This GitHub repository has already been imported.")

    try:
        github_repository = await get_repository(payload.github_url)
    except GitHubRepositoryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except GitHubRateLimitError as error:
        raise HTTPException(status_code=429, detail=str(error)) from error
    except GitHubApiError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    if not github_repository.default_branch:
        raise HTTPException(status_code=502, detail="GitHub did not provide a default branch for this repository.")

    try:
        tree_files = await get_repository_tree(
            github_repository.owner,
            github_repository.name,
            github_repository.default_branch,
        )
        contents = await get_text_file_contents(
            github_repository.owner,
            github_repository.name,
            tree_files,
        )
    except GitHubRateLimitError as error:
        raise HTTPException(status_code=429, detail=str(error)) from error
    except GitHubRepositoryNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except GitHubApiError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    # Check the API's canonical URL as well (important if GitHub redirects a
    # renamed repository).
    if db.scalar(select(Repository).where(Repository.github_url == github_repository.github_url)):
        raise HTTPException(status_code=409, detail="This GitHub repository has already been imported.")

    repository = Repository(
        name=github_repository.name,
        github_url=github_repository.github_url,
        description=github_repository.description,
        default_branch=github_repository.default_branch,
        owner=github_repository.owner,
        stars=github_repository.stars,
        forks=github_repository.forks,
        primary_language=github_repository.primary_language,
    )
    repository.files = [
        RepositoryFile(
            path=file.path,
            filename=file.path.rsplit("/", maxsplit=1)[-1],
            extension=_file_extension(file.path),
            language=_language_for_path(file.path),
            size=file.size,
            github_sha=file.github_sha,
            content=contents.get(file.path),
        )
        for file in tree_files
    ]
    db.add(repository)
    try:
        # Flush first so the repository and all RepositoryFile rows have their
        # database IDs.  Chunking then runs in this same transaction, rather
        # than requiring callers to invoke the separate processing endpoint.
        db.flush()
        chunk_result = process_repository_chunks(db, repository)
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="This GitHub repository has already been imported.") from error
    except Exception:
        db.rollback()
        logger.exception("Repository import and chunking failed for %s", github_repository.github_url)
        raise HTTPException(status_code=500, detail="Unable to import and process repository source files.")
    db.refresh(repository)
    logger.info(
        "Imported repository id=%s with %s source files processed and %s chunks created",
        repository.id,
        chunk_result.files_processed,
        chunk_result.chunks_created,
    )
    return repository


@router.get("/{repository_id}/files", response_model=RepositoryFileTreeResponse)
def get_repository_file_tree(repository_id: int, db: Session = Depends(get_db)) -> RepositoryFileTreeResponse:
    """Return stored file metadata for a previously imported repository."""
    repository = db.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found.")

    files = db.scalars(
        select(RepositoryFile)
        .where(RepositoryFile.repository_id == repository_id)
        .order_by(RepositoryFile.path)
    ).all()
    return RepositoryFileTreeResponse(
        repository_id=repository_id,
        files=[
            RepositoryFileResponse(
                id=file.id,
                path=file.path,
                filename=file.filename,
                extension=file.extension,
                language=file.language,
                size=file.size,
                github_sha=file.github_sha,
                has_content=file.content is not None,
            )
            for file in files
        ],
    )


@router.post("/{repository_id}/chunks/process", response_model=ChunkProcessingResponse)
def process_repository(repository_id: int, db: Session = Depends(get_db)) -> ChunkProcessingResponse:
    """Create fresh line-preserving chunks from a repository's stored source files."""
    repository = db.get(Repository, repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found.")

    try:
        result = process_repository_chunks(db, repository)
        db.commit()
    except Exception as error:
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to process repository source files.") from error

    return ChunkProcessingResponse(
        repository_id=repository_id,
        files_processed=result.files_processed,
        chunks_created=result.chunks_created,
    )


@router.post("/{repository_id}/tests/generate", response_model=TestGenerationResponse)
def generate_repository_tests(
    repository_id: int,
    payload: TestGenerationRequest,
    db: Session = Depends(get_db),
) -> TestGenerationResponse:
    """Generate review-required unit tests from one stored repository source file."""
    if db.get(Repository, repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found.")
    file = db.scalar(
        select(RepositoryFile).where(
            RepositoryFile.repository_id == repository_id,
            RepositoryFile.path == payload.path,
        )
    )
    if file is None:
        raise HTTPException(status_code=404, detail="Source file not found in this repository.")
    max_chunks, max_context_characters = generation_limits()
    chunks = db.scalars(
        select(CodeChunk)
        .where(
            CodeChunk.repository_id == repository_id,
            CodeChunk.repository_file_id == file.id,
        )
        .order_by(CodeChunk.chunk_index)
    ).all()
    selected_chunks = select_file_chunks(chunks, payload.focus, max_chunks)
    if not selected_chunks:
        raise HTTPException(
            status_code=409,
            detail="The selected file has no indexed source chunks. Process repository chunks first.",
        )
    try:
        result = generate_tests(
            file,
            selected_chunks,
            payload.focus,
            get_llm_provider(),
            max_context_characters,
        )
    except LLMProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except Exception as error:
        logger.exception("Unit-test generation failed for repository id=%s path=%s", repository_id, file.path)
        raise HTTPException(status_code=500, detail="Unable to generate unit tests.") from error
    return TestGenerationResponse(
        repository_id=repository_id,
        source_file_path=file.path,
        language=result.language,
        framework=result.framework,
        test_file_path=result.test_file_path,
        explanation=result.explanation,
        test_code=result.test_code,
        source_chunks=result.source_chunks,
        review_notice="Generated tests are suggestions only. Review and adapt them before adding them to your repository.",
    )


def _file_extension(path: str) -> str | None:
    filename = path.rsplit("/", maxsplit=1)[-1]
    if "." not in filename or filename.startswith("."):
        return None
    return f".{filename.rsplit('.', maxsplit=1)[-1].lower()}"


def _imported_repository_response(repository: Repository) -> ImportedRepositoryResponse:
    full_name = f"{repository.owner}/{repository.name}" if repository.owner else repository.name
    return ImportedRepositoryResponse(
        id=repository.id,
        owner=repository.owner,
        name=repository.name,
        full_name=full_name,
        github_url=repository.github_url,
        description=repository.description,
        language=repository.primary_language,
        default_branch=repository.default_branch,
        stars=repository.stars,
        forks=repository.forks,
        created_at=repository.created_at,
    )


def _language_for_path(path: str) -> str | None:
    extensions = {
        ".css": "CSS", ".go": "Go", ".html": "HTML", ".java": "Java",
        ".js": "JavaScript", ".json": "JSON", ".md": "Markdown", ".php": "PHP",
        ".py": "Python", ".rb": "Ruby", ".rs": "Rust", ".sh": "Shell",
        ".sql": "SQL", ".ts": "TypeScript", ".tsx": "TSX", ".yaml": "YAML", ".yml": "YAML",
    }
    return extensions.get(_file_extension(path) or "")
