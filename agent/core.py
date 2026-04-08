import base64
import json
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
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
    HISTORY_FILE,
    MAX_API_CALLS_PER_RUN,
    MAX_FILE_CONTENT_LENGTH,
    MAX_RETRIES,
    MISTRAL_MODEL,
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
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": GITHUB_MEDIA_TYPE,
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": f"github-contribution-agent/{username}",
        }
    )

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


class GitHubAgent:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.github_token = config.github_token
        self.mistral_api_key = config.mistral_api_key
        self.github_username = config.github_username
        self._api_calls = 0
        self._max_calls = (
            config.max_api_calls
            if hasattr(config, "max_api_calls")
            else MAX_API_CALLS_PER_RUN
        )

        self.session = _make_session(self.github_token, self.github_username)
        self.mistral = Mistral(api_key=self.mistral_api_key)
        self._processed_files: set = self._load_history()

    def _load_history(self) -> set:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if HISTORY_FILE.exists():
            try:
                data = json.loads(HISTORY_FILE.read_text())
                return set(data.get("processed_files", []))
            except (json.JSONDecodeError, IOError):
                return set()
        return set()

    def _save_history(self):
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {"processed_files": list(self._processed_files)}
        HISTORY_FILE.write_text(json.dumps(data, indent=2))

    def _mark_processed(self, repo_name: str, file_path: str):
        key = f"{repo_name}/{file_path}"
        self._processed_files.add(key)
        self._save_history()
        logger.info(f"Marked as processed: {key}")

    def _is_processed(self, repo_name: str, file_path: str) -> bool:
        key = f"{repo_name}/{file_path}"
        return key in self._processed_files

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
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
            self._api_calls += 1
            self._check_rate_limit(resp)
            return resp
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            socket.gaierror,
        ) as e:
            logger.error(f"Network error reaching GitHub: {e}")
            return None

    def _put(self, url: str, **kwargs) -> Optional[requests.Response]:
        try:
            resp = self.session.put(url, timeout=REQUEST_TIMEOUT, **kwargs)
            self._api_calls += 1
            self._check_rate_limit(resp)
            return resp
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            socket.gaierror,
        ) as e:
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

            repos.append(
                Repository(
                    full_name=r["full_name"],
                    name=r["name"],
                    default_branch=r.get("default_branch", "main"),
                    description=r.get("description"),
                    language=r.get("language"),
                    topics=r.get("topics", []),
                )
            )

        logger.info(f"Found {len(repos)} owned repos")
        return repos

    def get_repo_files(
        self, repo_full_name: str, default_branch: str = "main"
    ) -> list[RepoFile]:
        branches_to_try = [default_branch, "main", "master", "develop", "dev"]

        for branch in branches_to_try:
            url = f"{GITHUB_API_BASE}/repos/{repo_full_name}/git/trees/{branch}?recursive=1"
            resp = self._get(url)

            if resp and resp.status_code == 200:
                break
        else:
            return []

        data = resp.json()
        if not isinstance(data, dict) or "tree" not in data:
            return []

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
                    language=SUPPORTED_EXTENSIONS[ext],
                )
            )

        return files

    def get_file_content(self, repo_full_name: str, file_path: str) -> Optional[str]:
        url = f"{GITHUB_API_BASE}/repos/{repo_full_name}/contents/{file_path}"
        resp = self._get(url)

        if resp is None or resp.status_code != 200:
            return None

        data = resp.json()
        if data.get("encoding") == "base64":
            try:
                return base64.b64decode(data["content"]).decode(
                    "utf-8", errors="replace"
                )
            except Exception as e:
                logger.error(f"Failed to decode file content: {e}")
                return None

        return None

    def get_file_sha(self, repo_full_name: str, file_path: str) -> Optional[str]:
        url = f"{GITHUB_API_BASE}/repos/{repo_full_name}/contents/{file_path}"
        resp = self._get(url)

        if resp is not None and resp.status_code == 200:
            return resp.json().get("sha")

        return None

    def pick_contribution_target(
        self, repos: list[Repository]
    ) -> Optional[ContributionTarget]:
        import random

        random.shuffle(repos)

        for repo in repos:
            files = self.get_repo_files(repo.full_name, repo.default_branch)
            if not files:
                continue

            random.shuffle(files)
            for f in files:
                if self._is_processed(repo.full_name, f.path):
                    logger.debug(
                        f"Skipping already processed: {repo.full_name}/{f.path}"
                    )
                    continue

                content = self.get_file_content(repo.full_name, f.path)
                if content and len(content) > 100:
                    return ContributionTarget(
                        repo=repo,
                        file=f,
                        content=content,
                        language=f.language,
                    )

        return None

    def ask_mistral(self, prompt: str) -> Optional[str]:
        try:
            response = self.mistral.chat.complete(
                model=MISTRAL_MODEL,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Mistral API error: {e}")
            return None

    def generate_contribution(
        self, target: ContributionTarget
    ) -> Optional[Contribution]:
        content = target.content

        if len(content) > MAX_FILE_CONTENT_LENGTH:
            content = content[:MAX_FILE_CONTENT_LENGTH] + "\n... (truncated)"

        prompt = f"""You are a careful open-source contributor.
Analyze this {target.language} file named '{target.file.name}' and make ONE small, genuine improvement.

Rules:
- Fix a TODO comment, improve a docstring, add missing comments, fix a typo in a comment/string, or improve README content
- Keep changes minimal — only change what you need to
- Do NOT change logic or functionality
- Return ONLY a JSON object with these keys:
  - "improved_code": the full file with your change applied
  - "commit_message": a clear git commit message (max 72 chars)
  - "description": one sentence explaining what you changed and why

File content:
```
{content}
```

Return ONLY valid JSON, no markdown fences."""

        raw = self.ask_mistral(prompt)
        if not raw:
            logger.error("No response from Mistral")
            return None

        raw = re.sub(r"^```json\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw.strip())

        try:
            result = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Mistral response: {e}")
            return None

        required_keys = ["improved_code", "commit_message", "description"]
        if not all(k in result for k in required_keys):
            logger.warning("Mistral response missing required keys")
            return None

        if result["improved_code"].strip() == target.content.strip():
            logger.info("Mistral made no changes — skipping")
            return None

        return Contribution(
            improved_code=result["improved_code"],
            commit_message=result["commit_message"],
            description=result["description"],
        )

    def push_contribution(
        self, target: ContributionTarget, contribution: Contribution
    ) -> bool:
        repo_name = target.repo.full_name
        file_path = target.file.path
        sha = self.get_file_sha(repo_name, file_path)

        if not sha:
            logger.error("Could not get file SHA")
            return False

        encoded = base64.b64encode(contribution.improved_code.encode("utf-8")).decode(
            "utf-8"
        )

        url = f"{GITHUB_API_BASE}/repos/{repo_name}/contents/{file_path}"
        payload = {
            "message": contribution.commit_message,
            "content": encoded,
            "sha": sha,
        }

        resp = self._put(url, json=payload)

        if resp is not None and resp.status_code in (200, 201):
            logger.info(f"Pushed: {contribution.commit_message}")
            self._mark_processed(repo_name, file_path)
            return True

        error_msg = getattr(resp, "text", "no response") if resp else "no response"
        logger.error(
            f"Push failed: {getattr(resp, 'status_code', 'no response')} - {error_msg}"
        )
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
            message="Contribution ready for review",
            job=ContributionJob(target=target, contribution=contribution),
        )

    def apply(self, job: ContributionJob) -> bool:
        return self.push_contribution(job.target, job.contribution)
