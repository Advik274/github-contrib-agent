import base64
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Thread
from typing import Optional

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
    MISTRAL_TIMEOUT,
    REQUEST_TIMEOUT,
    RETRY_BACKOFF_FACTOR,
    SUPPORTED_EXTENSIONS,
)

logger = logging.getLogger(__name__)


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


class GitHubAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"GitHub API Error ({status_code}): {message}")


class RateLimitError(Exception):
    def __init__(self, reset_time: Optional[int] = None):
        self.reset_time = reset_time
        wait_time = max(0, reset_time - int(time.time())) + 5 if reset_time else 60
        super().__init__(f"Rate limit exceeded. Try again in {wait_time} seconds.")


def _make_session(token: str, username: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": GITHUB_MEDIA_TYPE,
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": f"github-contribution-agent/{username}",
    })

    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF_FACTOR,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "PUT", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


class HibernatingAgent:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.github_token = config.github_token
        self.mistral_api_key = config.mistral_api_key
        self.github_username = config.github_username
        self._max_calls = config.max_api_calls if hasattr(config, 'max_api_calls') else MAX_API_CALLS_PER_RUN

        self._session: Optional[requests.Session] = None
        self._mistral: Optional[Mistral] = None
        self._api_calls = 0

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

    def _check_rate_limit(self, resp: requests.Response) -> None:
        remaining = resp.headers.get("x-ratelimit-remaining")
        reset = resp.headers.get("x-ratelimit-reset")

        if remaining is not None and reset is not None:
            remaining = int(remaining)
            reset_time = int(reset)

            logger.debug(f"Rate limit remaining: {remaining}")

            if remaining < 10:
                wait = max(0, reset_time - int(time.time())) + 5
                logger.warning(f"Rate limit nearly exhausted. Sleeping {wait}s...")
                time.sleep(wait)

    def _get(self, url: str, **kwargs) -> Optional[requests.Response]:
        if self._api_calls >= self._max_calls:
            logger.warning("API call budget exhausted for this run")
            return None

        try:
            session = self._ensure_session()
            resp = session.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
            self._api_calls += 1
            self._check_rate_limit(resp)
            return resp
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, socket.gaierror) as e:
            logger.error(f"Network error reaching GitHub: {e}")
            return None

    def _put(self, url: str, **kwargs) -> Optional[requests.Response]:
        try:
            session = self._ensure_session()
            resp = session.put(url, timeout=REQUEST_TIMEOUT, **kwargs)
            self._api_calls += 1
            self._check_rate_limit(resp)
            return resp
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, socket.gaierror) as e:
            logger.error(f"Network error on PUT: {e}")
            return None

    def get_user_repos(self) -> list[Repository]:
        url = f"{GITHUB_API_BASE}/user/repos?per_page=100&type=owner&sort=updated"
        resp = self._get(url)

        if resp is None:
            logger.error("Failed to fetch repos: no response")
            return []

        if resp.status_code != 200:
            logger.error(f"Failed to fetch repos: {resp.status_code} - {resp.text}")
            return []

        repos = []
        for r in resp.json():
            if r.get("fork", False):
                continue

            repos.append(Repository(
                full_name=r["full_name"],
                name=r["name"],
                default_branch=r.get("default_branch", "main"),
                description=r.get("description"),
                language=r.get("language"),
                topics=r.get("topics", []),
            ))

        logger.info(f"Found {len(repos)} owned repos")
        return repos

    def get_repo_files(self, repo_name: str) -> list[RepoFile]:
        url = f"{GITHUB_API_BASE}/repos/{repo_name}/git/trees/main?recursive=1"
        resp = self._get(url)

        if resp is None or resp.status_code != 200:
            url = f"{GITHUB_API_BASE}/repos/{repo_name}/git/trees/master?recursive=1"
            resp = self._get(url)

        if resp is None or resp.status_code != 200:
            return []

        files = []
        for item in resp.json().get("tree", []):
            if item.get("type") != "blob":
                continue

            path = item["path"]
            ext = Path(path).suffix.lower()

            if ext not in SUPPORTED_EXTENSIONS:
                continue

            if item.get("size", 0) > MAX_FILE_CONTENT_LENGTH:
                continue

            if any(skip in path.lower() for skip in ["node_modules", ".git", "__pycache__", "venv", ".venv", "dist", "build"]):
                continue

            files.append(RepoFile(
                name=Path(path).name,
                path=path,
                sha=item.get("sha"),
                size=item.get("size", 0),
            ))

        return files

    def get_file_content(self, repo_name: str, file_path: str) -> Optional[str]:
        url = f"{GITHUB_API_BASE}/repos/{repo_name}/contents/{file_path}"
        resp = self._get(url)

        if resp is None or resp.status_code != 200:
            return None

        try:
            data = resp.json()
            if isinstance(data, dict) and "content" in data:
                import base64 as b64
                return b64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except Exception:
            pass

        return None

    def get_file_sha(self, repo_name: str, file_path: str) -> Optional[str]:
        url = f"{GITHUB_API_BASE}/repos/{repo_name}/contents/{file_path}"
        resp = self._get(url)

        if resp is None or resp.status_code != 200:
            return None

        data = resp.json()
        return data.get("sha") if isinstance(data, dict) else None

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

    def pick_contribution_target(self, repos: list[Repository]) -> Optional[ContributionTarget]:
        for repo in repos:
            files = self.get_repo_files(repo.full_name)
            if not files:
                continue

            for file in files[:15]:
                content = self.get_file_content(repo.full_name, file.path)
                if not content:
                    continue

                if len(content) < 100:
                    continue

                has_opportunity = any(pattern in content.lower() for pattern in [
                    "todo", "fixme", "xxx", "hack", "note:",
                    "not implemented", "add docstring", "# add",
                    "pass  # todo", "# fix", "implement this",
                ])

                file.language = self._detect_language(file.path, content)

                if file.language in ["Python", "JavaScript", "TypeScript", "Java", "Markdown", "Text"]:
                    return ContributionTarget(
                        repo=repo,
                        file=file,
                        content=content,
                        language=file.language,
                    )

        return None

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

    def generate_contribution(self, target: ContributionTarget) -> Optional[Contribution]:
        prompt = self._build_prompt(target)

        try:
            client = self._ensure_mistral()
            chat_response = client.chat.complete(
                model=MISTRAL_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2048,
            )

            response_text = chat_response.choices[0].message.content.strip()

            if response_text.startswith("```"):
                response_text = re.sub(r"^```\w*\n?", "", response_text)
                response_text = re.sub(r"\n?```$", "", response_text)

            import json as json_lib
            data = json_lib.loads(response_text)

            return Contribution(
                improved_code=data["improved_code"],
                commit_message=data["commit_message"][:72],
                description=data["description"],
            )

        except Exception as e:
            logger.error(f"Mistral API error: {e}")
            return None

    def push_contribution(self, target: ContributionTarget, contribution: Contribution) -> bool:
        repo_name = target.repo.full_name
        file_path = target.file.path
        sha = self.get_file_sha(repo_name, file_path)

        if not sha:
            logger.error("Could not get file SHA")
            return False

        encoded = base64.b64encode(
            contribution.improved_code.encode("utf-8")
        ).decode("utf-8")

        url = f"{GITHUB_API_BASE}/repos/{repo_name}/contents/{file_path}"
        payload = {
            "message": contribution.commit_message,
            "content": encoded,
            "sha": sha,
        }

        resp = self._put(url, json=payload)

        if resp is not None and resp.status_code in (200, 201):
            logger.info(f"Pushed: {contribution.commit_message}")
            return True

        error_msg = getattr(resp, "text", "no response") if resp else "no response"
        logger.error(f"Push failed: {getattr(resp, 'status_code', 'no response')} - {error_msg}")
        return False

    def validate_credentials(self) -> tuple[bool, str]:
        url = f"{GITHUB_API_BASE}/user"
        resp = self._get(url)

        if resp is None:
            return False, "Network error - could not reach GitHub"

        if resp.status_code == 401:
            return False, "Invalid GitHub token"

        if resp.status_code == 403:
            return False, "Token lacks required permissions"

        if resp.status_code != 200:
            return False, f"GitHub API error: {resp.status_code}"

        user_data = resp.json()
        return True, f"Connected as: {user_data.get('login', 'unknown')}"

    def run(self) -> AgentResult:
        logger.info("Agent started")

        repos = self.get_user_repos()
        if not repos:
            return AgentResult(
                success=False,
                message="No repos found or failed to fetch repos",
                error="Failed to fetch GitHub repositories",
            )

        target = self.pick_contribution_target(repos)
        if not target:
            return AgentResult(
                success=False,
                message="No suitable contribution target found",
                error="No improvable files found in repositories",
            )

        logger.info(f"Target: {target.repo.full_name} -> {target.file.path}")

        contribution = self.generate_contribution(target)
        if not contribution:
            return AgentResult(
                success=False,
                message="Could not generate a contribution",
                error="Mistral could not generate improvements",
            )

        return AgentResult(
            success=True,
            message="Contribution ready",
            job=ContributionJob(target=target, contribution=contribution),
        )


class OptimizedScheduler:
    def __init__(self, interval_hours: float, on_run: callable, on_status: callable):
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
