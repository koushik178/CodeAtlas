"""Bounded, file-scoped unit-test generation using stored repository chunks."""

import json
import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Sequence

from app.config import load_environment
from app.models.code_chunk import CodeChunk
from app.models.repository_file import RepositoryFile
from app.services.llm import LLMProvider, LLMProviderError

DEFAULT_MAX_CHUNKS = 8
DEFAULT_MAX_CONTEXT_CHARS = 24_000
MAX_CHUNKS = 12
MAX_CONTEXT_CHARS = 48_000

TEST_SYSTEM_PROMPT = """You generate focused unit tests from the supplied source code only.
Use the detected language/framework recommendation when it is suitable; otherwise choose the smallest conventional test setup for the language and explain the assumption.
Test observable behavior, error cases, and important branches supported by the source. Do not invent unavailable modules, APIs, or repository behavior.
Return valid JSON only with exactly these string fields: test_file_path, framework, explanation, test_code.
test_code must contain complete test source code with no Markdown fences. explanation must briefly state the coverage and any assumptions.
Generated tests must be reviewed and adapted before use."""


@dataclass(frozen=True)
class TestGenerationResult:
    language: str
    framework: str
    test_file_path: str
    explanation: str
    test_code: str
    source_chunks: int


def generation_limits() -> tuple[int, int]:
    """Return bounded limits for the selected file's source context."""
    load_environment()
    return (
        _bounded_environment_int("TEST_GENERATION_MAX_CHUNKS", DEFAULT_MAX_CHUNKS, 1, MAX_CHUNKS),
        _bounded_environment_int("TEST_GENERATION_MAX_CONTEXT_CHARS", DEFAULT_MAX_CONTEXT_CHARS, 4_000, MAX_CONTEXT_CHARS),
    )


def select_file_chunks(chunks: Sequence[CodeChunk], focus: str | None, maximum_chunks: int) -> list[CodeChunk]:
    """Prefer chunks mentioning a requested function/module, then preserve file order."""
    if not focus or not focus.strip():
        return list(chunks[:maximum_chunks])
    normalized_focus = focus.strip().lower()
    matching = [chunk for chunk in chunks if normalized_focus in chunk.content.lower()]
    selected = matching or list(chunks)
    return selected[:maximum_chunks]


def generate_tests(
    file: RepositoryFile,
    chunks: Sequence[CodeChunk],
    focus: str | None,
    provider: LLMProvider,
    maximum_context_characters: int,
) -> TestGenerationResult:
    """Generate review-required tests from a bounded set of one file's chunks."""
    context = _build_file_context(file.path, chunks, maximum_context_characters)
    if not context:
        raise LLMProviderError("The selected file has no usable source context for test generation.")
    language, recommended_framework = detect_stack(file, chunks)
    focus_instruction = focus.strip() if focus and focus.strip() else "the most important public behavior in this file"
    prompt = f"""Selected source file: {file.path}
Detected language: {language}
Recommended test framework: {recommended_framework}
Requested function or module focus: {focus_instruction}

Source context:
{context}

Generate focused unit tests for the selected file. Return JSON only."""
    payload = _parse_response(provider.answer(TEST_SYSTEM_PROMPT, prompt))
    return TestGenerationResult(
        language=language,
        framework=_required_text(payload, "framework", 200),
        test_file_path=_required_text(payload, "test_file_path", 2_048),
        explanation=_required_text(payload, "explanation", 2_000),
        test_code=_required_text(payload, "test_code", 30_000),
        source_chunks=len(chunks),
    )


def detect_stack(file: RepositoryFile, chunks: Sequence[CodeChunk]) -> tuple[str, str]:
    """Infer a conservative language and common test framework from stored code."""
    extension = (file.extension or PurePosixPath(file.path).suffix).lower()
    content = "\n".join(chunk.content for chunk in chunks).lower()
    if extension == ".py":
        return "Python", "unittest" if "import unittest" in content else "pytest"
    if extension in {".ts", ".tsx", ".js", ".jsx"}:
        language = "TypeScript" if extension in {".ts", ".tsx"} else "JavaScript"
        if "from 'vitest'" in content or 'from "vitest"' in content or "vitest" in content:
            return language, "Vitest"
        if "jest" in content:
            return language, "Jest"
        return language, "Vitest or Jest"
    if extension == ".go":
        return "Go", "testing"
    if extension == ".java":
        return "Java", "JUnit 5"
    if extension == ".rb":
        return "Ruby", "RSpec"
    if extension == ".rs":
        return "Rust", "built-in #[test]"
    return file.language or "Unknown", "No framework confidently detected"


def _build_file_context(path: str, chunks: Sequence[CodeChunk], maximum_characters: int) -> str:
    sections: list[str] = []
    used = 0
    for chunk in chunks:
        section = f"[Lines {chunk.start_line}-{chunk.end_line}]\n{chunk.content.strip()}"
        separator = 2 if sections else 0
        if used + separator + len(section) > maximum_characters:
            break
        sections.append(section)
        used += separator + len(section)
    return "\n\n".join(sections)


def _parse_response(response: str) -> dict[str, object]:
    fenced = re.fullmatch(r"\s*```(?:json)?\s*(\{.*\})\s*```\s*", response, re.DOTALL)
    try:
        parsed = json.loads(fenced.group(1) if fenced else response.strip())
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise LLMProviderError("The LLM provider returned an invalid test-generation response.") from error
    if not isinstance(parsed, dict):
        raise LLMProviderError("The LLM provider returned an invalid test-generation response.")
    return parsed


def _required_text(payload: dict[str, object], field: str, maximum_length: int) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise LLMProviderError("The LLM provider returned an incomplete test-generation response.")
    return value.strip()[:maximum_length]


def _bounded_environment_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        configured = int(os.getenv(name, str(default)))
    except ValueError:
        configured = default
    return min(max(configured, minimum), maximum)
