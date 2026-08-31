"""Stage 3 embedding processing and semantic code-chunk search endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.code_chunk import CodeChunk
from app.models.repository import Repository
from app.services.embeddings import (
    EmbeddingProviderError,
    embed_repository_chunks,
    find_similar_chunks,
    get_embedding_provider,
)
from app.services.llm import LLMProviderError, get_llm_provider
from app.services.rag import answer_question
from app.services.review import ReviewFinding, retrieve_review_chunks, review_limits, review_repository

router = APIRouter(prefix="/api/repositories", tags=["semantic search"])
logger = logging.getLogger(__name__)


class EmbeddingProcessingResponse(BaseModel):
    repository_id: int
    chunks_pending: int
    chunks_embedded: int
    batches_completed: int
    model: str


class SimilaritySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8_000)
    limit: int = Field(default=5, ge=1, le=20)


class SimilaritySearchChunk(BaseModel):
    chunk_id: int
    repository_file_id: int
    path: str
    chunk_index: int
    content: str
    start_line: int
    end_line: int
    token_count: int
    cosine_distance: float
    similarity: float


class SimilaritySearchResponse(BaseModel):
    repository_id: int
    query: str
    model: str
    chunks: list[SimilaritySearchChunk]


class RepositoryQuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4_000)
    limit: int = Field(default=5, ge=1, le=8)


class SourceReferenceResponse(BaseModel):
    chunk_id: int
    path: str
    start_line: int
    end_line: int


class RepositoryAnswerResponse(BaseModel):
    repository_id: int
    question: str
    model: str
    answer: str
    sources: list[SourceReferenceResponse]


class CodeReviewRequest(BaseModel):
    max_findings: int = Field(default=10, ge=1, le=20)


class CodeReviewFindingResponse(BaseModel):
    severity: str
    category: str
    description: str
    file_path: str
    start_line: int
    end_line: int
    chunk_id: int
    suggested_improvement: str


class CodeReviewResponse(BaseModel):
    repository_id: int
    model: str
    findings: list[CodeReviewFindingResponse]
    scanned_chunks: int
    scanned_files: int
    scope_note: str


@router.post("/{repository_id}/embeddings/process", response_model=EmbeddingProcessingResponse)
def process_repository_embeddings(
    repository_id: int, db: Session = Depends(get_db)
) -> EmbeddingProcessingResponse:
    """Generate missing chunk embeddings; retry safely after a failed batch."""
    if db.get(Repository, repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found.")
    try:
        result = embed_repository_chunks(db, repository_id, get_embedding_provider())
    except EmbeddingProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except Exception as error:
        logger.exception("Embedding processing failed for repository id=%s", repository_id)
        raise HTTPException(status_code=500, detail="Unable to process repository embeddings.") from error
    return EmbeddingProcessingResponse(repository_id=repository_id, **result.__dict__)


@router.post("/{repository_id}/search", response_model=SimilaritySearchResponse)
def search_repository_chunks(
    repository_id: int,
    payload: SimilaritySearchRequest,
    db: Session = Depends(get_db),
) -> SimilaritySearchResponse:
    """Return relevant chunks only; Stage 3 intentionally does not call a chat LLM."""
    if db.get(Repository, repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found.")
    try:
        provider = get_embedding_provider()
        embedded_count = db.scalar(
            select(func.count()).select_from(CodeChunk).where(
                CodeChunk.repository_id == repository_id,
                CodeChunk.embedding.is_not(None),
                CodeChunk.embedding_model == provider.model,
            )
        )
        if not embedded_count:
            raise HTTPException(status_code=409, detail="Repository has no embeddings for the configured model. Process embeddings first.")
        matches = find_similar_chunks(db, repository_id, payload.query, payload.limit, provider)
    except HTTPException:
        raise
    except EmbeddingProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except Exception as error:
        logger.exception("Similarity search failed for repository id=%s", repository_id)
        raise HTTPException(status_code=500, detail="Unable to search repository chunks.") from error
    return SimilaritySearchResponse(
        repository_id=repository_id,
        query=payload.query,
        model=provider.model,
        chunks=[
            SimilaritySearchChunk(
                chunk_id=match.chunk.id,
                repository_file_id=match.chunk.repository_file_id,
                path=match.path,
                chunk_index=match.chunk.chunk_index,
                content=match.chunk.content,
                start_line=match.chunk.start_line,
                end_line=match.chunk.end_line,
                token_count=match.chunk.token_count,
                cosine_distance=match.distance,
                similarity=1 - match.distance,
            )
            for match in matches
        ],
    )


@router.post("/{repository_id}/ask", response_model=RepositoryAnswerResponse)
def ask_repository_question(
    repository_id: int,
    payload: RepositoryQuestionRequest,
    db: Session = Depends(get_db),
) -> RepositoryAnswerResponse:
    """Answer a question from embeddings belonging only to this repository."""
    if db.get(Repository, repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found.")
    try:
        embedding_provider = get_embedding_provider()
        embedded_count = db.scalar(
            select(func.count()).select_from(CodeChunk).where(
                CodeChunk.repository_id == repository_id,
                CodeChunk.embedding.is_not(None),
                CodeChunk.embedding_model == embedding_provider.model,
            )
        )
        if not embedded_count:
            raise HTTPException(
                status_code=409,
                detail="Repository has no embeddings for the configured model. Process embeddings first.",
            )
        matches = find_similar_chunks(
            db, repository_id, payload.question, payload.limit, embedding_provider
        )
        llm_provider = get_llm_provider()
        result = answer_question(payload.question, matches, llm_provider)
    except HTTPException:
        raise
    except (EmbeddingProviderError, LLMProviderError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except Exception as error:
        logger.exception("Repository question answering failed for repository id=%s", repository_id)
        raise HTTPException(status_code=500, detail="Unable to answer repository question.") from error
    return RepositoryAnswerResponse(
        repository_id=repository_id,
        question=payload.question,
        model=llm_provider.model,
        answer=result.answer,
        sources=[SourceReferenceResponse(**source.__dict__) for source in result.sources],
    )


@router.post("/{repository_id}/review", response_model=CodeReviewResponse)
def review_repository_code(
    repository_id: int,
    payload: CodeReviewRequest,
    db: Session = Depends(get_db),
) -> CodeReviewResponse:
    """Return source-grounded findings from a bounded repository code review."""
    if db.get(Repository, repository_id) is None:
        raise HTTPException(status_code=404, detail="Repository not found.")
    try:
        embedding_provider = get_embedding_provider()
        embedded_count = db.scalar(
            select(func.count()).select_from(CodeChunk).where(
                CodeChunk.repository_id == repository_id,
                CodeChunk.embedding.is_not(None),
                CodeChunk.embedding_model == embedding_provider.model,
            )
        )
        if not embedded_count:
            raise HTTPException(
                status_code=409,
                detail="Repository has no embeddings for the configured model. Process embeddings first.",
            )
        max_chunks, max_files, max_context_characters, configured_max_findings = review_limits()
        matches = retrieve_review_chunks(
            db, repository_id, embedding_provider, max_chunks, max_files
        )
        llm_provider = get_llm_provider()
        result = review_repository(
            matches,
            llm_provider,
            max_context_characters,
            min(payload.max_findings, configured_max_findings),
        )
    except HTTPException:
        raise
    except (EmbeddingProviderError, LLMProviderError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except Exception as error:
        logger.exception("Repository code review failed for repository id=%s", repository_id)
        raise HTTPException(status_code=500, detail="Unable to review repository code.") from error
    return CodeReviewResponse(
        repository_id=repository_id,
        model=llm_provider.model,
        findings=[_review_finding_response(finding) for finding in result.findings],
        scanned_chunks=result.scanned_chunks,
        scanned_files=result.scanned_files,
        scope_note=(
            "This is a bounded AI-assisted review of retrieved source chunks, not a static-analysis "
            "or correctness guarantee."
        ),
    )


def _review_finding_response(finding: ReviewFinding) -> CodeReviewFindingResponse:
    return CodeReviewFindingResponse(
        severity=finding.severity,
        category=finding.category,
        description=finding.description,
        file_path=finding.source.path,
        start_line=finding.source.start_line,
        end_line=finding.source.end_line,
        chunk_id=finding.source.chunk_id,
        suggested_improvement=finding.suggested_improvement,
    )
