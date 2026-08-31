"""Provider-neutral embedding generation and pgvector similarity search."""

from dataclasses import dataclass
import logging
import os
from typing import Protocol, Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import load_environment
from app.models.code_chunk import CodeChunk, EMBEDDING_DIMENSIONS
from app.models.repository_file import RepositoryFile

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
SUPPORTED_OPENAI_MODELS = {"text-embedding-3-small", "text-embedding-3-large"}


class EmbeddingProviderError(RuntimeError):
    """Raised when a configured embedding provider cannot create vectors."""


class EmbeddingProvider(Protocol):
    """Minimal provider boundary so a non-OpenAI implementation can replace it."""

    model: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding, in input order, for every non-empty text."""


class OpenAIEmbeddingProvider:
    """OpenAI implementation using a fixed pgvector-compatible dimension."""

    def __init__(self, api_key: str, model: str) -> None:
        if model not in SUPPORTED_OPENAI_MODELS:
            supported = ", ".join(sorted(SUPPORTED_OPENAI_MODELS))
            raise EmbeddingProviderError(
                f"OPENAI_EMBEDDING_MODEL must be one of: {supported}."
            )
        try:
            from openai import OpenAI
        except ImportError as error:
            raise EmbeddingProviderError("Install the 'openai' package to generate embeddings.") from error
        self._client = OpenAI(api_key=api_key)
        self.model = model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("Embedding input must contain only non-empty text.")
        try:
            response = self._client.embeddings.create(
                model=self.model,
                input=list(texts),
                dimensions=EMBEDDING_DIMENSIONS,
                encoding_format="float",
            )
        except Exception as error:
            raise EmbeddingProviderError("The embedding provider request failed.") from error

        vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
        if len(vectors) != len(texts) or any(len(vector) != EMBEDDING_DIMENSIONS for vector in vectors):
            raise EmbeddingProviderError("The embedding provider returned an unexpected vector dimension.")
        return vectors


def get_embedding_provider() -> EmbeddingProvider:
    """Build the configured provider without exposing API keys to callers."""
    load_environment()
    provider_name = os.getenv("EMBEDDING_PROVIDER", "openai").lower()
    if provider_name != "openai":
        raise EmbeddingProviderError(f"Unsupported EMBEDDING_PROVIDER: {provider_name}.")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EmbeddingProviderError("OPENAI_API_KEY is not configured.")
    model = os.getenv("OPENAI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
    return OpenAIEmbeddingProvider(api_key=api_key, model=model)


def embedding_batch_size() -> int:
    """Return a bounded request batch size suitable for the embeddings API."""
    try:
        configured = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
    except ValueError:
        configured = 32
    return min(max(configured, 1), 128)


@dataclass(frozen=True)
class EmbeddingProcessingResult:
    chunks_pending: int
    chunks_embedded: int
    batches_completed: int
    model: str


@dataclass(frozen=True)
class SimilarChunk:
    chunk: CodeChunk
    path: str
    distance: float


def embed_repository_chunks(
    db: Session, repository_id: int, provider: EmbeddingProvider
) -> EmbeddingProcessingResult:
    """Embed only missing/outdated chunks, committing each completed API batch."""
    pending_chunks = db.scalars(
        select(CodeChunk)
        .where(
            CodeChunk.repository_id == repository_id,
            or_(
                CodeChunk.embedding.is_(None),
                CodeChunk.embedding_model.is_(None),
                CodeChunk.embedding_model != provider.model,
            ),
        )
        .order_by(CodeChunk.id)
    ).all()

    embedded = 0
    completed_batches = 0
    size = embedding_batch_size()
    for start in range(0, len(pending_chunks), size):
        batch = pending_chunks[start:start + size]
        try:
            vectors = provider.embed([chunk.content for chunk in batch])
            if len(vectors) != len(batch):
                raise EmbeddingProviderError("The provider returned a partial embedding batch.")
            for chunk, vector in zip(batch, vectors, strict=True):
                chunk.embedding = vector
                chunk.embedding_model = provider.model
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "Embedding batch failed: repository_id=%s batch_start=%s batch_size=%s",
                repository_id,
                start,
                len(batch),
            )
            raise
        embedded += len(batch)
        completed_batches += 1
        logger.info(
            "Embedded repository id=%s: batch=%s chunks=%s",
            repository_id,
            completed_batches,
            len(batch),
        )

    logger.info(
        "Embedding processing complete: repository_id=%s pending=%s embedded=%s batches=%s model=%s",
        repository_id,
        len(pending_chunks),
        embedded,
        completed_batches,
        provider.model,
    )
    return EmbeddingProcessingResult(
        chunks_pending=len(pending_chunks),
        chunks_embedded=embedded,
        batches_completed=completed_batches,
        model=provider.model,
    )


def find_similar_chunks(
    db: Session,
    repository_id: int,
    query: str,
    limit: int,
    provider: EmbeddingProvider,
) -> list[SimilarChunk]:
    """Embed a query and return nearest repository chunks by cosine distance."""
    query_vector = provider.embed([query])[0]
    distance = CodeChunk.embedding.cosine_distance(query_vector).label("distance")
    rows = db.execute(
        select(CodeChunk, RepositoryFile.path, distance)
        .join(RepositoryFile, RepositoryFile.id == CodeChunk.repository_file_id)
        .where(
            CodeChunk.repository_id == repository_id,
            CodeChunk.embedding.is_not(None),
            CodeChunk.embedding_model == provider.model,
        )
        .order_by(distance)
        .limit(limit)
    ).all()
    return [SimilarChunk(chunk=chunk, path=path, distance=float(value)) for chunk, path, value in rows]
