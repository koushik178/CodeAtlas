"""Application environment configuration."""

import os
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIRECTORY / ".env"


def load_environment() -> None:
    """Load backend/.env without replacing variables supplied by the host."""
    load_dotenv(ENV_FILE, override=False)


def get_csv_environment(name: str, default: str = "") -> list[str]:
    """Return a trimmed, non-empty comma-separated environment setting."""
    return [value.strip() for value in os.getenv(name, default).split(",") if value.strip()]


def get_boolean_environment(name: str, default: bool) -> bool:
    """Read a strict boolean setting and fail early for deployment mistakes."""
    value = os.getenv(name, str(default)).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be a boolean value.")


def get_positive_integer_environment(name: str, default: int, *, minimum: int = 0) -> int:
    """Read a bounded integer setting without exposing configuration values."""
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer.") from error
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}.")
    return value
