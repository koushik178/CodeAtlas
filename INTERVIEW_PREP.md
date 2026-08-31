# CodeAtlas interview preparation

## Resume bullets

- Built CodeAtlas, a full-stack repository intelligence application that imports public GitHub codebases, indexes line-addressable source chunks, and supports semantic code search and cited repository Q&A.
- Designed a FastAPI and PostgreSQL/pgvector retrieval pipeline using SQLAlchemy, OpenAI embeddings, repository-scoped cosine similarity, and bounded context assembly to keep AI outputs tied to source files and line ranges.
- Delivered a Next.js/TypeScript interface and Docker-based deployment workflow with health checks, CORS controls, backend reliability tests, and CI checks for frontend tests, linting, type checking, and production builds.

## 30-second explanation

CodeAtlas helps a developer get oriented in an unfamiliar public GitHub repository. It imports selected source files, splits them into line-addressable chunks, and stores embeddings in PostgreSQL with pgvector. From there, a developer can search semantically, ask questions with source references, run a bounded AI-assisted review, or generate test suggestions for a file. The key design choice is grounding each workflow in retrieved repository code rather than sending an entire codebase directly to a model.

## Two-minute technical explanation

CodeAtlas is a Next.js frontend backed by a FastAPI service and PostgreSQL with pgvector. The user supplies a public GitHub URL. The backend validates that URL, calls GitHub’s REST API for metadata and the default-branch tree, then fetches only eligible text blobs within explicit safety limits. It stores repository metadata, files, and source content through SQLAlchemy.

The indexing stage uses deterministic, line-preserving chunking. Chunks overlap slightly so boundaries retain local context, and each one records its source file plus start and end lines. An embedding endpoint creates OpenAI embeddings in batches and persists them in a 1,536-dimension pgvector field. It tracks the embedding model so it can detect chunks that need re-embedding after a model change.

For semantic search, the backend embeds the query and runs a cosine-distance query restricted to the selected repository. For Q&A, it uses those matches to build a bounded prompt with stable source labels, calls the chat model, and returns only the source references included in the prompt. Review similarly retrieves a bounded, diverse set of code chunks and asks for structured, source-supported findings. Test generation is narrower: it selects chunks from one chosen file and returns a suggestion with a reminder to review it.

Operationally, the services are containerized. Compose provides a local pgvector database, backend, and frontend; `/health` serves liveness and `/readyz` verifies database access. CI runs backend tests against temporary pgvector PostgreSQL and runs frontend tests, linting, type checking, and a production build. I would emphasize that the AI features are deliberately bounded and source-grounded, but they are not presented as a replacement for static analysis or human review.

## Likely architecture questions

### Why use pgvector instead of a separate vector database?

PostgreSQL already stores CodeAtlas’s repository, file, and chunk metadata. pgvector keeps vectors and relational metadata together, so repository-scoped retrieval can use ordinary SQL joins and filters, transactions remain simple, and the deployment has one persistence system. A separate vector database may be appropriate later if scale, indexing options, or operational separation require it.

### How do you prevent answers from mixing code from different repositories?

Every chunk carries a `repository_id`. Retrieval queries filter by the requested repository ID before ordering by cosine distance. The Q&A response sources are derived only from those retrieved chunks, so the context is repository-scoped end to end.

### How do you make AI outputs verifiable?

Chunking preserves the source file path and start/end line range. The retrieval layer carries that metadata into the Q&A context and response. Review findings also map back to trusted source metadata. The product still states clearly that generated outputs require human review.

### Why chunk by lines rather than parsing every language into an AST?

Line-preserving chunks work across the supported file types without requiring a parser for each language, and lines are immediately useful to a developer verifying a result. The tradeoff is that chunks do not understand syntax boundaries perfectly. Language-aware chunking is a good future improvement.

### How do you control cost and prompt size?

The design limits imported content, processes embeddings in configurable batches, retrieves only a small number of chunks, and applies maximum context bounds for Q&A, review, and test generation. Review and test generation have separate chunk and context limits because their tasks need different scopes.

### What happens if the embedding model changes?

Each chunk stores the model used for its embedding. The embedding-processing route treats missing embeddings or embeddings created by a different model as pending, then re-embeds them. Search and generation require vectors matching the currently configured model.

### How is importing made safe and reliable?

The importer accepts only canonical public GitHub URLs, rejects oversized or truncated trees, filters binary/generated/dependency content, and uses configurable limits on the number and size of downloaded files. It returns explicit HTTP errors for missing repositories, rate limits, and upstream failures. The repository, files, and chunks are stored together in a transaction during import.

### What would you change for production scale?

I would move imports and embedding jobs to a queue with durable job status and retries, add a vector index strategy informed by measured data, introduce authentication and per-user authorization, add repository refresh and incremental indexing, and instrument latency, errors, queue depth, and retrieval quality. I would make those decisions from production measurements rather than claim a specific performance threshold in advance.

### Why are code review and test generation described as bounded?

They do not scan or reason over an entire repository at once. Review uses a capped set of retrieved chunks and files; test generation uses capped chunks from one selected file. Boundaries make cost and context explicit and reduce the risk of implying exhaustive analysis.
