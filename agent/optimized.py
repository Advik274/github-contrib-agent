import base64
import json
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from threading import Event, Thread
from typing import Callable, Optional

import requests
from mistralai import Mistral
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import AgentConfig
from .constants import (
    GITHUB_API_BASE,
    GITHUB_API_VERSION,
    GITHUB_MEDIA_TYPE,
    MAX_API_CALLS_PER_RUN,
    MAX_FILE_CONTENT_LENGTH,
    MAX_RETRIES,
    MISTRAL_MODEL,
    REQUEST_TIMEOUT,
    RETRY_BACKOFF_FACTOR,
    SUPPORTED_EXTENSIONS,
)

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RepoFile:
    name: str
    path: str
    sha: Optional[str] = None
    size: int = 0
    language: str = "Unknown"


@dataclass
class Repository:
    full_name: str
    name: str
    default_branch: str
    description: Optional[str] = None
    language: Optional[str] = None
    topics: list[str] = field(default_factory=list)


@dataclass
class ContributionTarget:
    repo: Repository
    file: RepoFile
    content: str
    language: str


@dataclass
class Contribution:
    improved_code: str
    commit_message: str
    description: str


@dataclass
class ContributionJob:
    target: ContributionTarget
    contribution: Contribution
    created_at: float = field(default_factory=time.time)


@dataclass
class AgentResult:
    success: bool
    message: str
    job: Optional[ContributionJob] = None
    error: Optional[str] = None
    error_severity: ErrorSeverity = ErrorSeverity.MEDIUM
    retry_recommended: bool = False


@dataclass
class AgentError(Exception):
    message: str
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    retryable: bool = False
    details: Optional[str] = None

    def __str__(self):
        base = f"[{self.severity.value.upper()}] {self.message}"
        if self.details:
            base += f" | Details: {self.details}"
        return base


class NetworkError(AgentError):
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message, ErrorSeverity.MEDIUM, retryable=True, details=details)


class AuthenticationError(AgentError):
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message, ErrorSeverity.HIGH, retryable=False, details=details)


class RateLimitError(AgentError):
    def __init__(
        self,
        message: str,
        reset_time: Optional[int] = None,
        details: Optional[str] = None,
    ):
        wait_time = max(0, reset_time - int(time.time())) if reset_time else None
        details = details or (
            f"Retry after {wait_time}s" if wait_time else "Unknown reset time"
        )
        super().__init__(message, ErrorSeverity.MEDIUM, retryable=True, details=details)
        self.reset_time = reset_time


class APIError(AgentError):
    def __init__(self, status_code: int, message: str, details: Optional[str] = None):
        super().__init__(
            message,
            ErrorSeverity.HIGH if status_code >= 500 else ErrorSeverity.MEDIUM,
            retryable=status_code >= 500,
            details=details,
        )
        self.status_code = status_code


class ValidationError(AgentError):
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message, ErrorSeverity.LOW, retryable=False, details=details)


class ContentError(AgentError):
    def __init__(self, message: str, details: Optional[str] = None):
        super().__init__(message, ErrorSeverity.LOW, retryable=False, details=details)


ERROR_MESSAGES = {
    400: ("Bad request", False),
    401: ("Invalid or expired GitHub token", False),
    403: ("Access forbidden - check token permissions", False),
    404: ("Resource not found", False),
    409: ("Conflict - file may have been modified", True),
    410: ("Resource gone", False),
    422: ("Unprocessable entity - invalid data", False),
    451: ("Unavailable for legal reasons", False),
    500: ("GitHub server error", True),
    502: ("Bad gateway", True),
    503: ("Service unavailable", True),
    504: ("Gateway timeout", True),
}


def _make_session(token: str, username: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": GITHUB_MEDIA_TYPE,
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": f"github-contrib-agent/{username}",
        }
    )

    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF_FACTOR,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "PUT", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=5)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


class HibernatingAgent:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.github_token = config.github_token
        self.mistral_api_key = config.mistral_api_key
        self.github_username = config.github_username
        self._max_calls = (
            config.max_api_calls
            if hasattr(config, "max_api_calls")
            else MAX_API_CALLS_PER_RUN
        )

        self._session: Optional[requests.Session] = None
        self._mistral: Optional[Mistral] = None
        self._api_calls = 0
        self._last_error: Optional[AgentError] = None

    def _ensure_session(self) -> requests.Session:
        if self._session is None:
            self._session = _make_session(self.github_token, self.github_username)
        return self._session

    def _ensure_mistral(self) -> Mistral:
        if self._mistral is None:
            self._mistral = Mistral(api_key=self.mistral_api_key)
        return self._mistral

    def hibernate(self) -> None:
        if self._session:
            self._session.close()
            self._session = None
        self._mistral = None
        self._api_calls = 0
        logger.debug("Agent hibernated - connections closed")

    def _handle_rate_limit(self, resp: requests.Response) -> Optional[float]:
        remaining = resp.headers.get("x-ratelimit-remaining")
        reset = resp.headers.get("x-ratelimit-reset")

        if remaining is not None and reset is not None:
            remaining = int(remaining)
            reset_time = int(reset)

            logger.debug(f"Rate limit remaining: {remaining}/{self._max_calls}")

            if remaining < 5:
                wait = max(0, reset_time - int(time.time())) + 5
                logger.warning(f"Rate limit critical ({remaining}). Waiting {wait}s...")
                time.sleep(wait)
                return wait

            if remaining < 15:
                wait = max(0, reset_time - int(time.time())) + 5
                logger.warning(
                    f"Rate limit warning ({remaining}). Consider waiting {wait}s..."
                )

        return None

    def _handle_error_response(
        self, resp: requests.Response, context: str
    ) -> AgentError:
        status_code = resp.status_code
        msg, retryable = ERROR_MESSAGES.get(status_code, ("Unknown error", True))

        try:
            error_data = resp.json()
            details = error_data.get(
                "message", error_data.get("error", resp.text[:200])
            )
        except (json.JSONDecodeError, ValueError):
            details = resp.text[:200] if resp.text else "No response body"

        if status_code == 403:
            if "resource not accessible" in details.lower():
                return AuthenticationError(
                    "Classic PAT required for Contents API",
                    f"Fine-grained PATs don't support this operation. Details: {details}",
                )
            return AuthenticationError(f"Access denied: {msg}", details)

        if status_code == 401:
            return AuthenticationError("GitHub token is invalid or expired", details)

        return APIError(status_code, f"{context}: {msg}", details)

    def _validate_json_response(
        self, resp: requests.Response, expected_keys: list[str]
    ) -> Optional[dict]:
        try:
            data = resp.json()
            if not isinstance(data, dict):
                logger.error(f"Expected dict response, got {type(data)}")
                return None

            for key in expected_keys:
                if key not in data:
                    logger.error(f"Missing expected key '{key}' in response")
                    return None

            return data
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Invalid JSON response: {e}")
            return None

    def _get(
        self, url: str, **kwargs
    ) -> tuple[Optional[requests.Response], Optional[AgentError]]:
        if self._api_calls >= self._max_calls:
            logger.warning("API call budget exhausted for this run")
            return None, AgentError(
                "API call budget exhausted", ErrorSeverity.MEDIUM, retryable=True
            )

        try:
            session = self._ensure_session()
            resp = session.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
            self._api_calls += 1

            self._handle_rate_limit(resp)

            if resp.status_code >= 400:
                error = self._handle_error_response(resp, "GET request failed")
                self._last_error = error
                return None, error

            return resp, None

        except requests.exceptions.Timeout:
            error = NetworkError("Request timed out", f"URL: {url}")
            self._last_error = error
            logger.error(str(error))
            return None, error

        except requests.exceptions.ConnectionError as e:
            error = NetworkError("Connection failed", str(e))
            self._last_error = error
            logger.error(str(error))
            return None, error

        except socket.gaierror as e:
            error = NetworkError("DNS resolution failed", str(e))
            self._last_error = error
            logger.error(str(error))
            return None, error

        except Exception as e:
            error = AgentError(
                f"Unexpected error: {e}",
                ErrorSeverity.HIGH,
                retryable=True,
                details=str(e),
            )
            self._last_error = error
            logger.exception("Unexpected error in _get")
            return None, error

    def _put(
        self, url: str, **kwargs
    ) -> tuple[Optional[requests.Response], Optional[AgentError]]:
        try:
            session = self._ensure_session()
            resp = session.put(url, timeout=REQUEST_TIMEOUT, **kwargs)
            self._api_calls += 1

            self._handle_rate_limit(resp)

            if resp.status_code >= 400:
                error = self._handle_error_response(resp, "PUT request failed")
                self._last_error = error
                return None, error

            return resp, None

        except requests.exceptions.Timeout:
            error = NetworkError("PUT request timed out", f"URL: {url}")
            self._last_error = error
            logger.error(str(error))
            return None, error

        except requests.exceptions.ConnectionError as e:
            error = NetworkError("PUT connection failed", str(e))
            self._last_error = error
            logger.error(str(error))
            return None, error

        except Exception as e:
            error = AgentError(
                f"Unexpected PUT error: {e}",
                ErrorSeverity.HIGH,
                retryable=True,
                details=str(e),
            )
            self._last_error = error
            logger.exception("Unexpected error in _put")
            return None, error

    def get_user_repos(self) -> tuple[list[Repository], Optional[AgentError]]:
        url = f"{GITHUB_API_BASE}/user/repos?per_page=100&type=owner&sort=updated"
        resp, error = self._get(url)

        if error:
            logger.error(f"Failed to fetch repos: {error}")
            return [], error

        if resp is None:
            return [], AgentError(
                "No response from GitHub", ErrorSeverity.HIGH, retryable=True
            )

        if resp.status_code != 200:
            error = self._handle_error_response(resp, "Failed to fetch repos")
            return [], error

        repos = []
        for r in resp.json():
            if not isinstance(r, dict):
                logger.warning(f"Skipping invalid repo entry: {type(r)}")
                continue

            if r.get("fork", False):
                continue

            try:
                repos.append(
                    Repository(
                        full_name=r.get("full_name", ""),
                        name=r.get("name", ""),
                        default_branch=r.get("default_branch", "main"),
                        description=r.get("description"),
                        language=r.get("language"),
                        topics=r.get("topics", []) or [],
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to parse repo: {e}")
                continue

        logger.info(f"Found {len(repos)} owned repos")
        return repos, None

    def get_repo_files(
        self, repo_name: str
    ) -> tuple[list[RepoFile], Optional[AgentError]]:
        url = f"{GITHUB_API_BASE}/repos/{repo_name}/git/trees/main?recursive=1"
        resp, error = self._get(url)

        if error and error.severity == ErrorSeverity.HIGH and not error.retryable:
            branch = "master"
            url = f"{GITHUB_API_BASE}/repos/{repo_name}/git/trees/{branch}?recursive=1"
            resp, error = self._get(url)

        if error:
            logger.error(f"Failed to fetch files for {repo_name}: {error}")
            return [], error

        if resp is None or resp.status_code != 200:
            return [], AgentError(
                f"Could not fetch files for {repo_name}",
                ErrorSeverity.MEDIUM,
                retryable=True,
            )

        data = resp.json()
        if not isinstance(data, dict) or "tree" not in data:
            return [], ValidationError(
                "Invalid tree response", f"Response: {str(data)[:100]}"
            )

        files = []
        for item in data.get("tree", []):
            if not isinstance(item, dict):
                continue

            if item.get("type") != "blob":
                continue

            path = item.get("path", "")
            if not path:
                continue

            ext = Path(path).suffix.lower()

            if ext not in SUPPORTED_EXTENSIONS:
                continue

            if item.get("size", 0) > MAX_FILE_CONTENT_LENGTH:
                continue

            skip_patterns = [
                "node_modules",
                ".git",
                "__pycache__",
                "venv",
                ".venv",
                "dist",
                "build",
                ".venv",
                "env",
                "egg-info",
            ]
            if any(skip in path.lower() for skip in skip_patterns):
                continue

            files.append(
                RepoFile(
                    name=Path(path).name,
                    path=path,
                    sha=item.get("sha"),
                    size=item.get("size", 0),
                )
            )

        return files, None

    def get_file_content(
        self, repo_name: str, file_path: str
    ) -> tuple[Optional[str], Optional[AgentError]]:
        url = f"{GITHUB_API_BASE}/repos/{repo_name}/contents/{file_path}"
        resp, error = self._get(url)

        if error:
            return None, error

        if resp is None or resp.status_code != 200:
            return None, ContentError(f"Could not fetch content for {file_path}")

        data = resp.json()
        if not isinstance(data, dict):
            return None, ValidationError("Invalid content response")

        if "content" not in data:
            return None, ContentError(
                "No content in response", f"Keys: {list(data.keys())}"
            )

        try:
            content = base64.b64decode(data["content"]).decode(
                "utf-8", errors="replace"
            )
            return content, None
        except Exception as e:
            return None, ContentError(f"Failed to decode content: {e}")

    def get_file_sha(
        self, repo_name: str, file_path: str
    ) -> tuple[Optional[str], Optional[AgentError]]:
        url = f"{GITHUB_API_BASE}/repos/{repo_name}/contents/{file_path}"
        resp, error = self._get(url)

        if error:
            return None, error

        if resp is None or resp.status_code != 200:
            return None, ContentError(f"Could not fetch SHA for {file_path}")

        data = resp.json()
        if not isinstance(data, dict) or "sha" not in data:
            return None, ValidationError("No SHA in response")

        return data["sha"], None

    def _detect_language(self, path: str, content: str) -> str:
        ext = Path(path).suffix.lower()

        language_map = {
            ".py": "Python",
            ".java": "Java",
            ".c": "C",
            ".cpp": "C++",
            ".h": "C",
            ".hpp": "C++",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".jsx": "JavaScript",
            ".tsx": "TypeScript",
            ".go": "Go",
            ".rs": "Rust",
            ".rb": "Ruby",
            ".md": "Markdown",
            ".rst": "Markdown",
            ".txt": "Text",
        }

        if ext in language_map:
            return language_map[ext]

        if content.startswith("#!/usr/bin/env python"):
            return "Python"

        return "Unknown"

    def pick_contribution_target(
        self, repos: list[Repository]
    ) -> tuple[Optional[ContributionTarget], Optional[AgentError]]:
        for repo in repos:
            files, error = self.get_repo_files(repo.full_name)
            if error:
                logger.warning(f"Error fetching files for {repo.full_name}: {error}")
                continue

            if not files:
                continue

            for file in files[:15]:
                content, error = self.get_file_content(repo.full_name, file.path)
                if error:
                    logger.warning(f"Error fetching content for {file.path}: {error}")
                    continue

                if not content or len(content) < 100:
                    continue

                file.language = self._detect_language(file.path, content)

                if file.language in [
                    "Python",
                    "JavaScript",
                    "TypeScript",
                    "Java",
                    "Markdown",
                    "Text",
                ]:
                    return (
                        ContributionTarget(
                            repo=repo,
                            file=file,
                            content=content,
                            language=file.language,
                        ),
                        None,
                    )

        return None, None

    def _build_prompt(self, target: ContributionTarget) -> str:
        return f"""You are a code improvement assistant. Analyze the following {target.language} code and suggest ONE meaningful improvement.

File: {target.file.path}
Repository: {target.repo.full_name}
Description: {target.repo.description or "No description"}

Code:
```
{target.content[:3000]}
```

Respond ONLY with valid JSON in this exact format:
{{
    "improved_code": "the full improved code (same language)",
    "commit_message": "a short commit message (max 72 chars)",
    "description": "brief description of what was improved"
}}

Rules:
- Keep improvements focused and single-purpose
- Add docstrings, comments, or fix TODOs if present
- Improve variable names if unclear
- Do NOT add new features
- Return ONLY the JSON, no additional text
"""

    def generate_contribution(
        self, target: ContributionTarget
    ) -> tuple[Optional[Contribution], Optional[AgentError]]:
        prompt = self._build_prompt(target)

        try:
            client = self._ensure_mistral()

            try:
                chat_response = client.chat.complete(
                    model=MISTRAL_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=2048,
                )
            except Exception as api_error:
                error_msg = str(api_error).lower()

                if "api key" in error_msg or "unauthorized" in error_msg:
                    return None, AuthenticationError(
                        "Invalid Mistral API key", str(api_error)
                    )
                if "rate limit" in error_msg or "429" in error_msg:
                    return None, RateLimitError(
                        "Mistral API rate limit exceeded", details=str(api_error)
                    )
                if "timeout" in error_msg:
                    return None, AgentError(
                        "Mistral API timeout",
                        ErrorSeverity.MEDIUM,
                        retryable=True,
                        details=str(api_error),
                    )

                return None, AgentError(
                    f"Mistral API error: {api_error}",
                    ErrorSeverity.MEDIUM,
                    retryable=True,
                    details=str(api_error),
                )

            if not chat_response or not chat_response.choices:
                return None, AgentError(
                    "Empty response from Mistral API",
                    ErrorSeverity.HIGH,
                    retryable=True,
                )

            response_text = chat_response.choices[0].message.content.strip()

            if not response_text:
                return None, AgentError(
                    "Empty content from Mistral", ErrorSeverity.HIGH, retryable=True
                )

            if response_text.startswith("```"):
                response_text = re.sub(r"^```\w*\n?", "", response_text)
                response_text = re.sub(r"\n?```$", "", response_text)

            try:
                data = json.loads(response_text)
            except json.JSONDecodeError as e:
                if "```" in response_text:
                    json_match = re.search(r"\{[^}]+\}", response_text, re.DOTALL)
                    if json_match:
                        data = json.loads(json_match.group())
                    else:
                        return None, ValidationError(
                            "Could not parse JSON from response",
                            f"Error: {e} | Preview: {response_text[:200]}",
                        )
                else:
                    return None, ValidationError(
                        "Invalid JSON from Mistral",
                        f"Error: {e} | Preview: {response_text[:200]}",
                    )

            required_keys = ["improved_code", "commit_message", "description"]
            for key in required_keys:
                if key not in data:
                    return None, ValidationError(
                        f"Missing required key '{key}' in response",
                        f"Keys present: {list(data.keys())}",
                    )

            if not data["improved_code"] or len(data["improved_code"].strip()) < 10:
                return None, ValidationError(
                    "Invalid improved_code - too short or empty"
                )

            commit_msg = str(data["commit_message"])[:72]
            if len(commit_msg) < 3:
                return None, ValidationError("Invalid commit_message - too short")

            return (
                Contribution(
                    improved_code=data["improved_code"],
                    commit_message=commit_msg,
                    description=str(data["description"])[:200],
                ),
                None,
            )

        except Exception as e:
            error = AgentError(
                f"Unexpected error generating contribution: {e}",
                ErrorSeverity.HIGH,
                retryable=True,
                details=str(e),
            )
            logger.exception("Error in generate_contribution")
            return None, error

    def push_contribution(
        self, target: ContributionTarget, contribution: Contribution
    ) -> tuple[bool, Optional[AgentError]]:
        repo_name = target.repo.full_name
        file_path = target.file.path

        sha, error = self.get_file_sha(repo_name, file_path)
        if error:
            return False, error

        if not sha:
            return False, ContentError(
                "Could not get file SHA - file may have been deleted",
                f"Repo: {repo_name}, File: {file_path}",
            )

        try:
            encoded = base64.b64encode(
                contribution.improved_code.encode("utf-8")
            ).decode("utf-8")
        except Exception as e:
            return False, ValidationError(f"Failed to encode content: {e}")

        url = f"{GITHUB_API_BASE}/repos/{repo_name}/contents/{file_path}"
        payload = {
            "message": contribution.commit_message,
            "content": encoded,
            "sha": sha,
        }

        resp, error = self._put(url, json=payload)

        if error:
            return False, error

        if resp is None:
            return False, AgentError(
                "No response from GitHub after push", ErrorSeverity.HIGH, retryable=True
            )

        if resp.status_code in (200, 201):
            logger.info(f"✅ Pushed: {contribution.commit_message}")
            return True, None

        error = self._handle_error_response(resp, "Push failed")
        return False, error

    def validate_credentials(self) -> tuple[bool, str, Optional[AgentError]]:
        url = f"{GITHUB_API_BASE}/user"
        resp, error = self._get(url)

        if error:
            if isinstance(error, AuthenticationError):
                return False, str(error), error
            return False, f"Network error: {error.message}", error

        if resp is None:
            return (
                False,
                "No response from GitHub",
                AgentError(
                    "No response during validation", ErrorSeverity.HIGH, retryable=True
                ),
            )

        user_data = resp.json()
        if not isinstance(user_data, dict):
            return (
                False,
                "Invalid response from GitHub",
                ValidationError("User data is not a valid dict"),
            )

        username = user_data.get("login", "unknown")
        logger.info(f"Validated credentials for: {username}")
        return True, f"Connected as: {username}", None

    def get_last_error(self) -> Optional[AgentError]:
        return self._last_error

    def run(self) -> AgentResult:
        logger.info("Agent run starting...")

        repos, error = self.get_user_repos()
        if error:
            return AgentResult(
                success=False,
                message="Failed to fetch repositories",
                error=str(error),
                error_severity=error.severity,
                retry_recommended=error.retryable,
            )

        if not repos:
            return AgentResult(
                success=False,
                message="No repositories found",
                error="No owned repositories found. Create some repos to contribute to!",
                error_severity=ErrorSeverity.LOW,
            )

        target, error = self.pick_contribution_target(repos)
        if error:
            return AgentResult(
                success=False,
                message="Error scanning repositories",
                error=str(error),
                error_severity=error.severity,
                retry_recommended=error.retryable,
            )

        if not target:
            return AgentResult(
                success=False,
                message="No suitable files found for improvement",
                error="No improvable files found in your repositories",
                error_severity=ErrorSeverity.LOW,
            )

        logger.info(f"Target: {target.repo.full_name} -> {target.file.path}")

        contribution, error = self.generate_contribution(target)
        if error:
            return AgentResult(
                success=False,
                message="Failed to generate improvement",
                error=str(error),
                error_severity=error.severity,
                retry_recommended=error.retryable,
            )

        if not contribution:
            return AgentResult(
                success=False,
                message="No contribution generated",
                error="Mistral returned empty response",
                error_severity=ErrorSeverity.HIGH,
                retry_recommended=True,
            )

        return AgentResult(
            success=True,
            message="Contribution ready",
            job=ContributionJob(target=target, contribution=contribution),
        )


class OptimizedScheduler:
    def __init__(self, interval_hours: float, on_run: Callable, on_status: Callable):
        self.interval_seconds = interval_hours * 3600
        self.on_run = on_run
        self.on_status = on_status
        self._stop_event = Event()
        self._thread: Optional[Thread] = None

    def start(self, run_on_start: bool = True) -> None:
        self._stop_event.clear()
        self._thread = Thread(target=self._run, args=(run_on_start,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self, run_on_start: bool) -> None:
        self.on_status("idle")

        if run_on_start:
            time.sleep(2)
            self.on_run()
        else:
            self.on_status("idle")

        while not self._stop_event.is_set():
            next_run = time.time() + self.interval_seconds

            while time.time() < next_run and not self._stop_event.is_set():
                time.sleep(1)

            if not self._stop_event.is_set():
                self.on_run()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
