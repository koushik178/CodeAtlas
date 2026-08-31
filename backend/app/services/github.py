"""Small, focused client for GitHub's public repository API."""

import asyncio
from dataclasses import dataclass
import os
import re
from urllib.parse import quote, urlparse

import httpx

from app.config import load_environment


class InvalidGitHubUrlError(ValueError):
    """Raised when a URL is not a public github.com repository URL."""


class GitHubRepositoryNotFoundError(Exception):
    """Raised when GitHub reports that a repository does not exist."""


class GitHubApiError(Exception):
    """Raised when GitHub cannot provide a usable API response."""


class GitHubRateLimitError(GitHubApiError):
    """Raised when GitHub refuses a request because its API limit was reached."""


@dataclass(frozen=True)
class GitHubRepository:
    name: str
    github_url: str
    description: str | None
    default_branch: str | None
    owner: str
    stars: int
    forks: int
    primary_language: str | None


@dataclass(frozen=True)
class GitHubTreeFile:
    """One blob entry returned from GitHub's recursive tree endpoint."""

    path: str
    github_sha: str
    size: int | None


def parse_github_repository_url(repository_url: str) -> tuple[str, str]:
    """Return owner/repository from a canonical public GitHub web URL."""
    parsed = urlparse(repository_url.strip())
    try:
        valid_port = parsed.port is None
    except ValueError:
        valid_port = False
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or not valid_port
    ):
        raise InvalidGitHubUrlError("Provide a public https://github.com/owner/repository URL.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise InvalidGitHubUrlError("GitHub URLs must contain exactly an owner and repository name.")

    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[:-4]
    owner_pattern = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
    repository_pattern = r"[A-Za-z0-9._-]{1,100}"
    if not re.fullmatch(owner_pattern, owner) or not re.fullmatch(repository_pattern, repository):
        raise InvalidGitHubUrlError("GitHub owner and repository names are invalid.")
    return owner, repository


async def get_repository(repository_url: str) -> GitHubRepository:
    """Fetch public repository metadata from GitHub's REST API."""
    owner, repository = parse_github_repository_url(repository_url)
    response = await _get_api_response(f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}")

    if response.status_code == 404:
        raise GitHubRepositoryNotFoundError("The GitHub repository was not found or is not public.")
    _raise_for_api_error(response)

    try:
        payload = response.json()
        owner_login = payload["owner"]["login"]
        name = payload["name"]
        github_url = payload["html_url"]
    except (KeyError, TypeError, ValueError) as error:
        raise GitHubApiError("GitHub API returned an unexpected response.") from error

    return GitHubRepository(
        name=name,
        github_url=github_url,
        description=payload.get("description"),
        default_branch=payload.get("default_branch"),
        owner=owner_login,
        stars=payload.get("stargazers_count", 0),
        forks=payload.get("forks_count", 0),
        primary_language=payload.get("language"),
    )


async def get_repository_tree(owner: str, repository: str, default_branch: str) -> list[GitHubTreeFile]:
    """Return a bounded recursive file tree for the requested branch."""
    response = await _get_api_response(
        f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}/git/trees/"
        f"{quote(default_branch, safe='')}?recursive=1"
    )
    if response.status_code == 404:
        raise GitHubRepositoryNotFoundError("The repository's default branch was not found.")
    _raise_for_api_error(response)
    try:
        payload = response.json()
        tree = payload["tree"]
    except (KeyError, TypeError, ValueError) as error:
        raise GitHubApiError("GitHub API returned an unexpected file tree response.") from error

    if payload.get("truncated"):
        raise GitHubApiError("Repository file tree is too large for safe import.")

    files = [
        GitHubTreeFile(path=item["path"], github_sha=item["sha"], size=item.get("size"))
        for item in tree
        if item.get("type") == "blob"
    ]
    max_files = _environment_positive_int("GITHUB_MAX_TREE_FILES", 2000)
    if len(files) > max_files:
        raise GitHubApiError(f"Repository has more than the safe limit of {max_files} files.")
    return files


async def get_text_file_contents(
    owner: str, repository: str, files: list[GitHubTreeFile]
) -> dict[str, str | None]:
    """Fetch eligible blob contents, bounded by per-file and total-size limits."""
    # 50 content requests plus metadata/tree requests stays below GitHub's
    # unauthenticated hourly limit; authenticated deployments can raise it.
    max_content_files = _environment_positive_int("GITHUB_MAX_CONTENT_FILES", 50)
    max_file_bytes = _environment_positive_int("GITHUB_MAX_FILE_BYTES", 524_288)
    max_total_bytes = _environment_positive_int("GITHUB_MAX_TOTAL_CONTENT_BYTES", 8_388_608)
    selected: list[GitHubTreeFile] = []
    total_size = 0
    for file in files:
        if not is_text_file_candidate(file.path, file.size, max_file_bytes):
            continue
        file_size = file.size or 0
        if len(selected) >= max_content_files or total_size + file_size > max_total_bytes:
            continue
        selected.append(file)
        total_size += file_size

    semaphore = asyncio.Semaphore(5)

    async def fetch_one(file: GitHubTreeFile) -> tuple[str, str | None]:
        async with semaphore:
            response = await _get_api_response(
                f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}/git/blobs/"
                f"{quote(file.github_sha, safe='')}",
                accept="application/vnd.github.raw+json",
            )
            _raise_for_api_error(response)
            raw_content = response.content
            if len(raw_content) > max_file_bytes or b"\x00" in raw_content:
                return file.path, None
            try:
                return file.path, raw_content.decode("utf-8")
            except UnicodeDecodeError:
                return file.path, None

    return dict(await asyncio.gather(*(fetch_one(file) for file in selected)))


def is_text_file_candidate(path: str, size: int | None, max_file_bytes: int) -> bool:
    """Exclude generated, binary, dependency, and oversized files from content fetches."""
    excluded_directories = {".git", ".next", ".venv", "build", "dist", "node_modules", "out", "target", "vendor"}
    excluded_filenames = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "composer.lock", "cargo.lock", "poetry.lock"}
    excluded_extensions = {
        ".7z", ".avi", ".bmp", ".class", ".dll", ".doc", ".docx", ".exe", ".gif", ".gz", ".ico", ".jar", ".jpeg", ".jpg", ".lock", ".mp3", ".mp4", ".pdf", ".png", ".so", ".tar", ".ttf", ".wav", ".webp", ".woff", ".woff2", ".zip",
    }
    parts = path.lower().split("/")
    filename = parts[-1]
    extension = os.path.splitext(filename)[1]
    return (
        not any(directory in excluded_directories for directory in parts[:-1])
        and filename not in excluded_filenames
        and extension not in excluded_extensions
        and (size is None or size <= max_file_bytes)
    )


async def _get_api_response(path: str, accept: str = "application/vnd.github+json") -> httpx.Response:
    load_environment()
    headers = {"Accept": accept, "User-Agent": "CodeAtlas"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    base_url = os.getenv("GITHUB_API_BASE_URL", "https://api.github.com").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            return await client.get(f"{base_url}{path}", headers=headers)
    except httpx.HTTPError as error:
        raise GitHubApiError("Unable to reach the GitHub API.") from error


def _raise_for_api_error(response: httpx.Response) -> None:
    if response.headers.get("X-RateLimit-Remaining") == "0" or response.status_code in {403, 429}:
        raise GitHubRateLimitError("GitHub API rate limit reached. Add GITHUB_TOKEN or try again later.")
    if response.is_error:
        raise GitHubApiError(f"GitHub API returned HTTP {response.status_code}.")


def _environment_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default
