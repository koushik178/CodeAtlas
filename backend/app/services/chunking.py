"""Deterministic, line-preserving source code chunking."""

from dataclasses import dataclass
import logging
from pathlib import PurePosixPath

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.code_chunk import CodeChunk
from app.models.repository import Repository
from app.models.repository_file import RepositoryFile

logger = logging.getLogger(__name__)

# About 1,000 tokens for typical source code while keeping individual chunks
# comfortable for later embedding and answer-generation workflows.
CHUNK_SIZE_CHARS = 4_000
# Repeating ten source lines maintains local context across chunk boundaries.
CHUNK_OVERLAP_LINES = 10

CHUNKABLE_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".html", ".java",
    ".js", ".json", ".jsx", ".kt", ".kts", ".md", ".php", ".py", ".rb", ".rs",
    ".sh", ".sql", ".swift", ".toml", ".ts", ".tsx", ".vue", ".xml", ".yaml", ".yml",
}

EXCLUDED_PATH_PARTS = {
    ".git", ".next", ".venv", "__pycache__", "build", "dist", "node_modules",
    "out", "target", "vendor",
}
EXCLUDED_FILENAMES = {
    "cargo.lock", "composer.lock", "package-lock.json", "pnpm-lock.yaml",
    "poetry.lock", "yarn.lock",
}
GENERATED_FILENAME_SUFFIXES = (".min.js", ".min.css", ".generated.py", ".g.py")


@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    content: str
    start_line: int
    end_line: int
    token_count: int


@dataclass(frozen=True)
class ChunkProcessingResult:
    files_processed: int
    chunks_created: int


def chunk_source(content: str) -> list[ChunkDraft]:
    """Split text into overlapping, line-addressable chunks without splitting lines."""
    if not content.strip():
        return []

    lines = content.splitlines(keepends=True)
    chunks: list[ChunkDraft] = []
    start = 0
    while start < len(lines):
        end = start
        character_count = 0
        while end < len(lines):
            next_size = len(lines[end])
            if end > start and character_count + next_size > CHUNK_SIZE_CHARS:
                break
            character_count += next_size
            end += 1

        chunk_content = "".join(lines[start:end])
        chunks.append(
            ChunkDraft(
                chunk_index=len(chunks),
                content=chunk_content,
                start_line=start + 1,
                end_line=end,
                token_count=_approximate_token_count(chunk_content),
            )
        )
        if end == len(lines):
            break
        start = max(start + 1, end - CHUNK_OVERLAP_LINES)

    return chunks


def process_repository_chunks(db: Session, repository: Repository) -> ChunkProcessingResult:
    """Replace a repository's chunks with chunks from currently stored source files."""
    files = db.scalars(
        select(RepositoryFile).where(RepositoryFile.repository_id == repository.id)
    ).all()
    eligible_files = [file for file in files if _is_chunkable_file(file)]

    # Replacement is idempotent and occurs within the endpoint transaction:
    # an error rolls back both the removal and the attempted replacement.
    db.execute(delete(CodeChunk).where(CodeChunk.repository_id == repository.id))

    chunks_created = 0
    for file in eligible_files:
        for draft in chunk_source(file.content or ""):
            db.add(
                CodeChunk(
                    repository_id=repository.id,
                    repository_file_id=file.id,
                    chunk_index=draft.chunk_index,
                    content=draft.content,
                    start_line=draft.start_line,
                    end_line=draft.end_line,
                    token_count=draft.token_count,
                )
            )
            chunks_created += 1

    skipped_files = len(files) - len(eligible_files)
    logger.info(
        "Chunked repository id=%s: files_seen=%s files_processed=%s files_skipped=%s chunks_created=%s",
        repository.id,
        len(files),
        len(eligible_files),
        skipped_files,
        chunks_created,
    )
    return ChunkProcessingResult(
        files_processed=len(eligible_files), chunks_created=chunks_created
    )


def _approximate_token_count(content: str) -> int:
    """Estimate tokens without adding a tokenizer dependency before embeddings."""
    return max(1, (len(content) + 3) // 4)


def _is_chunkable_content(content: str) -> bool:
    """Avoid producing oversized chunks from minified or generated single lines."""
    return bool(content.strip()) and all(
        len(line) <= CHUNK_SIZE_CHARS for line in content.splitlines()
    )


def _is_chunkable_file(file: RepositoryFile) -> bool:
    """Select stored text/source files without depending on nullable language."""
    if file.content is None or not _is_chunkable_content(file.content):
        return False

    path = file.path.lower()
    path_parts = PurePosixPath(path).parts
    filename = path_parts[-1] if path_parts else path
    extension = (file.extension or PurePosixPath(filename).suffix).lower()

    # The importer already rejects these paths before retrieving content. Keep
    # the check here too so manually stored or older files are not chunked.
    if (
        any(part in EXCLUDED_PATH_PARTS for part in path_parts[:-1])
        or filename in EXCLUDED_FILENAMES
        or filename.endswith(GENERATED_FILENAME_SUFFIXES)
    ):
        return False

    # Extension/path drives eligibility.  `language` is intentionally not a
    # prerequisite: GitHub documentation and some source files may have NULL.
    return extension in CHUNKABLE_EXTENSIONS
