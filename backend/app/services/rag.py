"""Repository-scoped retrieval-augmented question answering helpers."""

import os
from dataclasses import dataclass
from typing import Sequence

from app.services.embeddings import SimilarChunk
from app.services.llm import LLMProvider

DEFAULT_MAX_CONTEXT_CHARS = 24_000
MIN_MAX_CONTEXT_CHARS = 4_000
MAX_MAX_CONTEXT_CHARS = 60_000

SYSTEM_PROMPT = """You answer questions about a software repository using only the supplied source context.
Do not use outside knowledge or infer repository-specific facts that are not supported by that context.
When the context does not contain enough evidence, say exactly what is missing or that the context is insufficient.
Use citations such as [Source 1] for claims about repository code. Do not mention sources that were not provided."""


@dataclass(frozen=True)
class SourceReference:
    chunk_id: int
    path: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class RepositoryAnswer:
    answer: str
    sources: list[SourceReference]


def context_character_limit() -> int:
    """Return a bounded context budget to keep LLM prompts predictable."""
    try:
        configured = int(os.getenv("RAG_MAX_CONTEXT_CHARS", str(DEFAULT_MAX_CONTEXT_CHARS)))
    except ValueError:
        configured = DEFAULT_MAX_CONTEXT_CHARS
    return min(max(configured, MIN_MAX_CONTEXT_CHARS), MAX_MAX_CONTEXT_CHARS)


def answer_question(
    question: str, matches: Sequence[SimilarChunk], provider: LLMProvider
) -> RepositoryAnswer:
    """Answer from selected repository chunks and return only included sources."""
    context, sources = build_context(matches, context_character_limit())
    if not sources:
        return RepositoryAnswer(
            answer="The retrieved repository context is insufficient to answer this question.",
            sources=[],
        )
    user_prompt = f"""Question:
{question}

Repository source context:
{context}

Answer the question only from the context above. Cite supporting statements with [Source N]."""
    return RepositoryAnswer(answer=provider.answer(SYSTEM_PROMPT, user_prompt), sources=sources)


def build_context(
    matches: Sequence[SimilarChunk], maximum_characters: int
) -> tuple[str, list[SourceReference]]:
    """Format whole chunks with stable source labels within a character budget."""
    sections: list[str] = []
    sources: list[SourceReference] = []
    used_characters = 0
    for match in matches:
        source_number = len(sources) + 1
        reference = SourceReference(
            chunk_id=match.chunk.id,
            path=match.path,
            start_line=match.chunk.start_line,
            end_line=match.chunk.end_line,
        )
        section = (
            f"[Source {source_number} | chunk_id={reference.chunk_id} | "
            f"path={reference.path} | lines={reference.start_line}-{reference.end_line}]\n"
            f"{match.chunk.content.strip()}"
        )
        separator_length = 2 if sections else 0
        if used_characters + separator_length + len(section) > maximum_characters:
            break
        sections.append(section)
        sources.append(reference)
        used_characters += separator_length + len(section)
    return "\n\n".join(sections), sources
