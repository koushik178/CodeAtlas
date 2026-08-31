"""Provider-neutral LLM completion for repository question answering."""

import os
from typing import Protocol

from app.config import load_environment

DEFAULT_LLM_MODEL = "gpt-4o-mini"


class LLMProviderError(RuntimeError):
    """Raised when the configured LLM cannot produce an answer."""


class LLMProvider(Protocol):
    """Small boundary for an LLM implementation used by RAG."""

    model: str

    def answer(self, system_prompt: str, user_prompt: str) -> str:
        """Return a text answer for the supplied prompts."""


class OpenAIChatProvider:
    """OpenAI Chat Completions implementation."""

    def __init__(self, api_key: str, model: str) -> None:
        try:
            from openai import OpenAI
        except ImportError as error:
            raise LLMProviderError("Install the 'openai' package to answer repository questions.") from error
        self._client = OpenAI(api_key=api_key)
        self.model = model

    def answer(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = response.choices[0].message.content
        except Exception as error:
            raise LLMProviderError("The LLM provider request failed.") from error

        if not content or not content.strip():
            raise LLMProviderError("The LLM provider returned an empty answer.")
        return content.strip()


def get_llm_provider() -> LLMProvider:
    """Build the configured LLM provider without exposing API keys to callers."""
    load_environment()
    provider_name = os.getenv("LLM_PROVIDER", "openai").lower()
    if provider_name != "openai":
        raise LLMProviderError(f"Unsupported LLM_PROVIDER: {provider_name}.")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise LLMProviderError("OPENAI_API_KEY is not configured.")
    return OpenAIChatProvider(api_key=api_key, model=os.getenv("OPENAI_CHAT_MODEL", DEFAULT_LLM_MODEL))
