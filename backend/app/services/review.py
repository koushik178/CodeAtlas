"""Bounded, source-grounded automated repository code review."""

import json
import os
import re
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy.orm import Session

from app.config import load_environment
from app.services.embeddings import EmbeddingProvider, SimilarChunk, find_similar_chunks
from app.services.llm import LLMProvider, LLMProviderError
from app.services.rag import SourceReference, build_context

DEFAULT_MAX_CHUNKS = 12
DEFAULT_MAX_FILES = 8
DEFAULT_MAX_CONTEXT_CHARS = 30_000
DEFAULT_MAX_FINDINGS = 10
MAX_CHUNKS = 20
MAX_FILES = 12
MAX_CONTEXT_CHARS = 60_000
MAX_FINDINGS = 20

REVIEW_QUERIES = (
    "potential bugs error handling edge cases validation state mutation maintainability",
    "security authentication authorization secrets input validation injection unsafe operations",
    "performance resource management database network calls algorithm efficiency code quality",
)

REVIEW_SYSTEM_PROMPT = """You are a careful repository code reviewer. Review only the supplied source context.
This is a limited AI-assisted review, not static analysis or a correctness guarantee. Report only concrete, actionable concerns supported by a supplied source label.
Do not claim vulnerabilities, bugs, or behavior that cannot be verified from the context. Do not report style-only preferences.
Consider bugs, maintainability, security, code_quality, and performance where evidence supports them.
Return valid JSON only, with this shape:
{"findings":[{"severity":"critical|high|medium|low","category":"bugs|maintainability|security|code_quality|performance","description":"brief evidence-based finding","source_number":1,"suggested_improvement":"specific improvement"}]}
Use source_number from the supplied [Source N] labels. Return an empty findings array when the context has no well-supported findings."""

VALID_SEVERITIES = {"critical", "high", "medium", "low"}
VALID_CATEGORIES = {"bugs", "maintainability", "security", "code_quality", "performance"}


@dataclass(frozen=True)
class ReviewFinding:
    severity: str
    category: str
    description: str
    suggested_improvement: str
    source: SourceReference


@dataclass(frozen=True)
class ReviewResult:
    findings: list[ReviewFinding]
    scanned_chunks: int
    scanned_files: int


def review_limits() -> tuple[int, int, int, int]:
    """Return bounded review limits configured by environment variables."""
    load_environment()
    return (
        _bounded_environment_int("CODE_REVIEW_MAX_CHUNKS", DEFAULT_MAX_CHUNKS, 1, MAX_CHUNKS),
        _bounded_environment_int("CODE_REVIEW_MAX_FILES", DEFAULT_MAX_FILES, 1, MAX_FILES),
        _bounded_environment_int("CODE_REVIEW_MAX_CONTEXT_CHARS", DEFAULT_MAX_CONTEXT_CHARS, 4_000, MAX_CONTEXT_CHARS),
        _bounded_environment_int("CODE_REVIEW_MAX_FINDINGS", DEFAULT_MAX_FINDINGS, 1, MAX_FINDINGS),
    )


def retrieve_review_chunks(
    db: Session,
    repository_id: int,
    provider: EmbeddingProvider,
    max_chunks: int,
    max_files: int,
) -> list[SimilarChunk]:
    """Retrieve a small, diverse set of repository-only review candidates."""
    matches: list[SimilarChunk] = []
    seen_chunks: set[int] = set()
    seen_files: set[str] = set()
    per_query_limit = min(max_chunks, 8)
    for query in REVIEW_QUERIES:
        for match in find_similar_chunks(db, repository_id, query, per_query_limit, provider):
            if match.chunk.id in seen_chunks:
                continue
            if match.path not in seen_files and len(seen_files) >= max_files:
                continue
            matches.append(match)
            seen_chunks.add(match.chunk.id)
            seen_files.add(match.path)
            if len(matches) >= max_chunks:
                return matches
    return matches


def review_repository(
    matches: Sequence[SimilarChunk], provider: LLMProvider, maximum_context_characters: int, maximum_findings: int
) -> ReviewResult:
    """Review retrieved chunks and map model findings back to trusted source metadata."""
    context, sources = build_context(matches, maximum_context_characters)
    if not sources:
        return ReviewResult(findings=[], scanned_chunks=0, scanned_files=0)
    prompt = f"""Repository source context:
{context}

Review this limited context. Return only source-supported findings in the required JSON format."""
    findings = parse_review_findings(provider.answer(REVIEW_SYSTEM_PROMPT, prompt), sources, maximum_findings)
    return ReviewResult(
        findings=findings,
        scanned_chunks=len(sources),
        scanned_files=len({source.path for source in sources}),
    )


def parse_review_findings(
    response: str, sources: Sequence[SourceReference], maximum_findings: int
) -> list[ReviewFinding]:
    """Validate LLM JSON and retain only findings tied to supplied source references."""
    try:
        payload = json.loads(_json_object(response))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise LLMProviderError("The LLM provider returned an invalid code review response.") from error
    raw_findings = payload.get("findings") if isinstance(payload, dict) else None
    if not isinstance(raw_findings, list):
        raise LLMProviderError("The LLM provider returned an invalid code review response.")

    findings: list[ReviewFinding] = []
    for item in raw_findings:
        if len(findings) >= maximum_findings or not isinstance(item, dict):
            break
        severity = item.get("severity")
        category = item.get("category")
        source_number = item.get("source_number")
        description = _clean_text(item.get("description"), 1_500)
        improvement = _clean_text(item.get("suggested_improvement"), 1_500)
        if (
            severity not in VALID_SEVERITIES
            or category not in VALID_CATEGORIES
            or not isinstance(source_number, int)
            or not 1 <= source_number <= len(sources)
            or not description
            or not improvement
        ):
            continue
        findings.append(
            ReviewFinding(
                severity=severity,
                category=category,
                description=description,
                suggested_improvement=improvement,
                source=sources[source_number - 1],
            )
        )
    return findings


def _json_object(value: str) -> str:
    """Accept a JSON object optionally wrapped in a Markdown code fence."""
    fenced = re.fullmatch(r"\s*```(?:json)?\s*(\{.*\})\s*```\s*", value, re.DOTALL)
    return fenced.group(1) if fenced else value.strip()


def _clean_text(value: object, maximum_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:maximum_length] or None


def _bounded_environment_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        configured = int(os.getenv(name, str(default)))
    except ValueError:
        configured = default
    return min(max(configured, minimum), maximum)
