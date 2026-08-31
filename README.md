# CodeAtlas

## Project overview

CodeAtlas is an AI-assisted codebase exploration tool for public GitHub repositories. It imports repository metadata and selected source files, creates line-addressable code chunks, stores semantic embeddings in PostgreSQL with pgvector, and provides a browser interface for repository Q&A, semantic search, bounded code review, and test-generation suggestions.

> AI-generated answers, review findings, and tests are assistance—not a substitute for human review, testing, security analysis, or production change control.

## The problem

Understanding an unfamiliar repository is slow: relevant code may be spread across files, documentation becomes stale, and keyword search does not capture intent. CodeAtlas gives developers a source-grounded way to navigate an imported public repository. Answers and review findings reference the file and line range of their supporting chunks, helping the user verify the result in the original code.

## Features

- Import a public `https://github.com/owner/repository` URL and display stored repository metadata.
- Fetch a bounded set of eligible text files from the repository’s default branch.
- Deterministically chunk supported source files while preserving line ranges and overlap for context.
- Generate and persist OpenAI embeddings in PostgreSQL using pgvector.
- Search repository chunks by cosine similarity.
- Ask source-grounded questions and receive cited file/line references.
- Run a bounded, AI-assisted code review with severity, category, and suggested improvement fields.
- Generate file-scoped unit-test suggestions with an explicit review notice.
- Run frontend and backend checks in CI, including a temporary pgvector PostgreSQL service for backend tests.

## Architecture

```mermaid
flowchart LR
    U[Developer] --> F[Next.js frontend]
    F -->|REST /api/repositories| B[FastAPI backend]
    B -->|metadata, tree, source blobs| G[GitHub REST API]
    B -->|embeddings and generation| O[OpenAI API]
    B -->|SQLAlchemy| P[(PostgreSQL + pgvector)]
    P --> R[Repositories, files, chunks, vectors]
```

### Import and retrieval flow

1. The backend validates a public GitHub URL, reads repository metadata and its default-branch tree, and fetches eligible text blobs within configured safety limits.
2. It stores repository and file records, then creates overlapping, line-addressable chunks for supported source files.
3. The embeddings endpoint generates vectors for missing or stale chunks and stores them alongside the embedding model name.
4. Search, Q&A, and review embed the request, retrieve only chunks from the selected repository by cosine distance, and return source metadata with results.

## Tech stack

| Layer | Technologies |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS |
| Backend | Python 3.13, FastAPI, Uvicorn, Pydantic |
| Persistence | PostgreSQL 16, pgvector, SQLAlchemy, Alembic |
| Integrations | GitHub REST API, OpenAI embeddings and chat completions |
| Quality & delivery | `unittest`, Vitest, Testing Library, ESLint, TypeScript, Docker, Docker Compose, GitHub Actions |

## Repository structure

```text
CodeAtlas/
├── backend/
│   ├── app/
│   │   ├── db/           # Engine, pgvector type, schema initialization
│   │   ├── models/       # Repository, file, and code-chunk ORM models
│   │   ├── routers/      # Import, search, Q&A, review, and test APIs
│   │   └── services/     # GitHub, chunking, embeddings, RAG, review, LLMs
│   ├── tests/            # Backend unit and reliability tests
│   └── Dockerfile
├── frontend/
│   ├── src/app/          # Next.js App Router UI and frontend tests
│   ├── public/
│   └── Dockerfile
├── .github/workflows/    # CI workflow
├── compose.yaml          # Frontend, backend, and pgvector stack
├── DEPLOYMENT.md         # Production deployment guidance
└── .env.example          # Docker Compose environment template
```

## Local setup

### Prerequisites

- Node.js 22 and npm
- Python 3.13
- Docker Desktop with Docker Compose (recommended for PostgreSQL + pgvector)
- An OpenAI API key for embeddings, Q&A, review, and test generation
- Optional: a GitHub token to increase GitHub API headroom for imports

### Option A: run the full stack with Docker Compose

1. Copy `.env.example` to `.env`.
2. Set `POSTGRES_PASSWORD` to a strong local password and set `OPENAI_API_KEY`. Set `GITHUB_TOKEN` if desired.
3. Keep `NEXT_PUBLIC_API_URL=http://localhost:8000` and `CORS_ALLOW_ORIGINS=http://localhost:3000` for local development.
4. Start the stack:

   ```bash
   docker compose --env-file .env up --build
   ```

5. Open `http://localhost:3000`. The API is available at `http://localhost:8000`; interactive API documentation is at `http://localhost:8000/docs`.

### Option B: run services locally

Start PostgreSQL with pgvector first (see the next section), then configure each application.

Backend:

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
Copy-Item .env.example .env  # PowerShell
# On macOS/Linux: cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Frontend (in a second terminal):

```bash
cd frontend
npm ci
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"  # PowerShell
# macOS/Linux: export NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Open `http://localhost:3000`. `NEXT_PUBLIC_API_URL` is bundled into the frontend during production builds, so build it again after changing the deployed API URL.

## Environment variables

Copy only the appropriate example file and never commit credentials. The root [`.env.example`](.env.example) is consumed by Compose; [`backend/.env.example`](backend/.env.example) documents backend settings.

| Variable | Used by | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Backend | SQLAlchemy PostgreSQL connection string. Required outside Compose. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Compose database | Local container database bootstrap values. |
| `NEXT_PUBLIC_API_URL` | Frontend / Compose | Browser-reachable API URL. Public; supplied at frontend build time. |
| `OPENAI_API_KEY` | Backend | Required for embeddings and generated responses. Keep secret. |
| `OPENAI_EMBEDDING_MODEL` | Backend | OpenAI embedding model; defaults to `text-embedding-3-small`. |
| `OPENAI_CHAT_MODEL` | Backend | Chat model used for Q&A, review, and tests; defaults to `gpt-4o-mini`. |
| `GITHUB_TOKEN` | Backend | Optional bearer token for GitHub API requests. |
| `CORS_ALLOW_ORIGINS` | Backend | Comma-separated browser origins; use exact production HTTPS origins. |
| `CORS_ALLOW_CREDENTIALS` | Backend | CORS credentials switch; do not combine with `*` origins. |
| `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `DATABASE_POOL_RECYCLE_SECONDS`, `DATABASE_POOL_PRE_PING` | Backend | SQLAlchemy connection-pool controls. |
| `EMBEDDING_BATCH_SIZE`, `RAG_MAX_CONTEXT_CHARS` | Backend | Embedding request batch size and Q&A context bound. |
| `CODE_REVIEW_MAX_CHUNKS`, `CODE_REVIEW_MAX_FILES`, `CODE_REVIEW_MAX_CONTEXT_CHARS`, `CODE_REVIEW_MAX_FINDINGS` | Backend | Bounds for AI-assisted review. |
| `TEST_GENERATION_MAX_CHUNKS`, `TEST_GENERATION_MAX_CONTEXT_CHARS` | Backend | Bounds for test-generation context. |

The GitHub service also supports advanced optional limits such as `GITHUB_MAX_TREE_FILES`, `GITHUB_MAX_CONTENT_FILES`, `GITHUB_MAX_FILE_BYTES`, and `GITHUB_MAX_TOTAL_CONTENT_BYTES`.

## PostgreSQL + pgvector

The provided Compose stack uses `pgvector/pgvector:pg16`, which is the simplest local option. For a separately managed instance:

1. Use PostgreSQL with the pgvector extension installed and make it reachable only from the backend.
2. Create a database and configure `DATABASE_URL`, for example:

   ```text
   postgresql+psycopg2://codeatlas:your-password@localhost:5432/codeatlas
   ```

3. Ensure the backend database role may run `CREATE EXTENSION IF NOT EXISTS vector` at first startup, or arrange for an administrator to enable `vector` beforehand.
4. Start the backend. It creates the application tables and verifies the extension before serving requests.

Code chunks use a 1,536-dimension pgvector column. The configured embedding provider must return matching vector dimensions; the included OpenAI provider requests that dimension explicitly.

## Running the frontend and backend

Use `docker compose --env-file .env up --build` to run all three services together. For local processes, start the FastAPI backend with `uvicorn app.main:app --reload --port 8000` from `backend/`, then run `npm run dev` from `frontend/` with `NEXT_PUBLIC_API_URL` set to the backend address.

## Testing

Run backend tests with a PostgreSQL database that has pgvector enabled and a matching `DATABASE_URL`:

```bash
cd backend
python -m unittest discover -s tests -v
```

Run frontend checks:

```bash
cd frontend
npm ci
npm test
npm run lint
npx tsc --noEmit
npm run build
```

GitHub Actions runs these backend and frontend checks on pushes and pull requests. The backend CI job starts a temporary pgvector PostgreSQL service; no deployment occurs in CI.

## API overview

FastAPI exposes OpenAPI documentation at `/docs` while the backend is running. Key routes use the `/api/repositories` prefix:

| Method | Route | Description |
| --- | --- | --- |
| `GET` | `/api/repositories` | List imported repositories. |
| `POST` | `/api/repositories/import` | Import a public GitHub repository. |
| `GET` | `/api/repositories/{id}/files` | List stored repository files. |
| `POST` | `/api/repositories/{id}/chunks/process` | Recreate chunks from stored source files. |
| `POST` | `/api/repositories/{id}/embeddings/process` | Create embeddings for missing or outdated chunks. |
| `POST` | `/api/repositories/{id}/search` | Return semantically similar chunks. |
| `POST` | `/api/repositories/{id}/ask` | Answer a source-grounded repository question. |
| `POST` | `/api/repositories/{id}/review` | Run a bounded AI-assisted code review. |
| `POST` | `/api/repositories/{id}/tests/generate` | Generate file-scoped test suggestions. |
| `GET` | `/health`, `/readyz` | Liveness and database-aware readiness probes. |

For the workflows that depend on vectors, import and process embeddings before calling search, ask, or review. Requests return validation errors for invalid input and surface missing embeddings or absent provider credentials as actionable API errors.

## Deployment overview

Deploy the frontend, backend, and PostgreSQL database as separate managed components, or use the supplied Compose configuration for a single host. Put the frontend and API behind HTTPS; keep PostgreSQL private and allow it to be reached only by the backend. Build the frontend with a browser-resolvable HTTPS `NEXT_PUBLIC_API_URL`, configure exact frontend origins in backend CORS settings, and store database, GitHub, and OpenAI credentials in the platform’s secret manager.

See [DEPLOYMENT.md](DEPLOYMENT.md) for container health checks, Compose steps, managed-service guidance, CORS configuration, and connection-pool sizing considerations.

## Screenshots

Add screenshots here as the UI is finalized. Recommended captures:

| Placeholder | Suggested content |
| --- | --- |
| `docs/images/repository-import.png` | Repository URL import and imported metadata |
| `docs/images/repository-qa.png` | Source-grounded question with cited file and line ranges |
| `docs/images/code-review.png` | AI-assisted findings with severity and suggested improvements |
| `docs/images/test-generation.png` | File-scoped generated test suggestion |

## Known limitations

- Only public `github.com` repository URLs are supported; private repositories and other hosts are out of scope.
- Imports deliberately apply file-count, file-size, total-size, binary, generated-file, and dependency-directory limits, so an imported index may not contain every repository file.
- Semantic retrieval, Q&A, review, and test generation require a configured OpenAI key and embeddings for the selected repository.
- Generated outputs can be incomplete or incorrect and must be reviewed; code review is not static analysis or a correctness/security guarantee.
- Repository content is imported from the default branch at import time; automatic synchronization with later upstream changes is not implemented.
- The embedding schema is fixed to 1,536 dimensions, limiting compatible embedding configurations without a schema change.

## Future improvements

- Add authenticated private-repository integrations and provider abstraction for additional git hosts.
- Support repository refresh, branch/ref selection, incremental indexing, and deletion lifecycle controls.
- Add background jobs, progress reporting, retries, and observability for large imports and embedding work.
- Add hybrid retrieval, reranking, configurable chunking, and evaluation datasets for retrieval quality.
- Add static-analysis integrations and diff-aware reviews alongside AI-assisted findings.
- Add user authentication, per-user repository access control, quotas, audit logs, and production telemetry.

## Interview preparation

See [INTERVIEW_PREP.md](INTERVIEW_PREP.md) for resume bullets, short and technical project explanations, and architecture interview questions with suggested answers.
