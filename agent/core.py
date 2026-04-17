import base64
import json
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

import requests
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
    REQUEST_TIMEOUT,
    RETRY_BACKOFF_FACTOR,
    SUPPORTED_EXTENSIONS,
    AI_TIMEOUT,
)

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────


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


# ── Generate-contribution outcome ─────────────────────────────────────────────


class GenerateOutcome(Enum):
    """
    Why generate_contribution() returned no contribution.

    Distinguishing API errors from "nothing to improve" is critical:
    - API_ERROR   → don't mark file processed; the file is fine, the API is broken
    - NO_CHANGE   → mark file processed; AI reviewed it and had nothing to do
    - PARSE_ERROR → mark file processed; response was garbled, move on
    """

    SUCCESS = auto()
    API_ERROR = auto()  # HTTP 4xx/5xx, timeout, network — don't blame the file
    NO_CHANGE = auto()  # AI returned unchanged code — file is "done"
    PARSE_ERROR = auto()  # AI response was unparseable — move on


# ── Improvement scoring ───────────────────────────────────────────────────────

_IMPROVEMENT_SIGNALS = [
    (r"#\s*TODO", 10, "has TODO"),
    (r"#\s*FIXME", 10, "has FIXME"),
    (r"//\s*TODO", 10, "has TODO"),
    (r"//\s*FIXME", 10, "has FIXME"),
    (r"raise\s+NotImplementedError", 9, "not implemented"),
    (r"def \w+\([^)]*\):\s*\n\s*(pass|\.\.\.)(\s*#.*)?$", 7, "stub function"),
    (r"#\s*HACK", 6, "has HACK comment"),
    (r"#\s*XXX", 5, "has XXX comment"),
    (r"def \w+\([^)]*\):\s*\n(?!\s*(\"\"\"|\'\'\'))", 4, "function missing docstring"),
    (r"^\s*(print|console\.log)\(", 2, "debug print left in"),
]


def _score_file(content: str, language: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    for pattern, points, label in _IMPROVEMENT_SIGNALS:
        try:
            matches = len(re.findall(pattern, content, re.MULTILINE))
        except re.error:
            continue
        if matches:
            score += points * min(matches, 3)
            reasons.append(f"{label} (×{matches})")
    lines = content.count("\n")
    if lines < 5:
        score -= 8
    elif lines > 500:
        score -= 3
    return max(0, score), reasons


# ── JSON response parser ──────────────────────────────────────────────────────


def _parse_ai_json(raw: str) -> Optional[dict]:
    if not raw:
        return None

    cleaned = raw.strip()

    if (
        cleaned.startswith("We are")
        or cleaned.startswith("Here is")
        or cleaned.startswith("The")
    ):
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            cleaned = match.group(0)

    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    brace_count = 0
    json_start = -1
    for i, c in enumerate(cleaned):
        if c == "{":
            if json_start == -1:
                json_start = i
            brace_count += 1
        elif c == "}":
            brace_count -= 1
            if brace_count == 0 and json_start != -1:
                candidate = cleaned[json_start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    break

    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    logger.debug(f"Could not parse AI JSON. Raw (first 300 chars): {raw[:300]}")
    return None


# ── GitHub session factory ────────────────────────────────────────────────────


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


# ── Universal AI client ───────────────────────────────────────────────────────


class AIError(Exception):
    """Raised by AIClient.complete_or_raise() on API-level failures."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class AIClient:
    """
    Universal AI client using the OpenAI-compatible chat completion REST API.
    Works with Google AI Studio, OpenRouter, Groq, Mistral, Together AI, OpenAI.

    complete()          → returns text or None (swallows all errors)
    complete_or_raise() → returns text or raises AIError (lets caller decide)
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {config.ai_api_key}",
                "Content-Type": "application/json",
            }
        )
        if config.ai_provider == "openrouter":
            self._session.headers[
                "HTTP-Referer"
            ] = "https://github.com/Advik274/github-contrib-agent"
            self._session.headers["X-Title"] = "GitHub Contribution Agent"

    def _post(self, prompt: str) -> str:
        """
        Core POST — raises AIError on any failure.
        Callers decide how to handle it.
        """
        api_base = self.config.provider_api_base().rstrip("/")
        model = self.config.effective_model()
        url = f"{api_base}/chat/completions"

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 2048,
        }

        try:
            resp = self._session.post(url, json=payload, timeout=AI_TIMEOUT)
        except requests.exceptions.Timeout:
            raise AIError(
                f"Request timed out after {AI_TIMEOUT}s ({self.config.ai_provider}/{model})"
            )
        except (requests.exceptions.ConnectionError, socket.gaierror) as e:
            raise AIError(f"Network error reaching {self.config.ai_provider}: {e}")

        if not resp.ok:
            body = resp.text[:300]
            status = resp.status_code

            # Produce a helpful message for the most common codes
            if status == 401:
                hint = "Invalid API key"
            elif status == 403:
                hint = "API key lacks permission"
            elif status == 404:
                hint = f"Model not found: '{model}'. Check the model name."
            elif status == 429:
                hint = "Rate limit / quota exceeded — wait or switch provider"
            elif status == 402:
                hint = "Insufficient credits — top up or switch provider"
            else:
                hint = f"HTTP {status}"

            logger.error(
                f"AI HTTP error ({self.config.ai_provider} / {model}): "
                f"{status} — {body}"
            )
            raise AIError(hint, status_code=status)

        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            return (text or "").strip()
        except (KeyError, IndexError) as e:
            raise AIError(f"Unexpected response format: {e}")

    def complete(self, prompt: str) -> Optional[str]:
        """Swallow all errors and return None on failure."""
        try:
            return self._post_with_retry(prompt) or None
        except AIError:
            return None

    def complete_or_raise(self, prompt: str) -> str:
        """Return text or raise AIError — lets callers distinguish API vs. logic errors."""
        return self._post_with_retry(prompt)

    def _post_with_retry(self, prompt: str, max_retries: int = 2) -> str:
        """POST with retry on transient errors (429 rate limit, 5xx server errors)."""
        last_error: Optional[AIError] = None
        for attempt in range(max_retries + 1):
            try:
                return self._post(prompt)
            except AIError as e:
                last_error = e
                should_retry = (
                    e.status_code in (429, 500, 502, 503, 504)
                    or "Rate limit" in str(e)
                    or "Network error" in str(e)
                    or "timeout" in str(e).lower()
                )
                if should_retry and attempt < max_retries:
                    wait = (attempt + 1) * 5
                    logger.warning(
                        f"AI call failed (attempt {attempt + 1}/{max_retries + 1}): {e} — "
                        f"retrying in {wait}s"
                    )
                    time.sleep(wait)
                else:
                    raise
        raise last_error or AIError("Unexpected retry failure")

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._post("Reply with the single word: ok")
            return True, (
                f"Connected to {self.config.ai_provider} "
                f"({self.config.effective_model()})"
            )
        except AIError as e:
            return False, str(e)


# ── Main GitHub agent ─────────────────────────────────────────────────────────


class GitHubAgent:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.github_token = config.github_token
        self.github_username = config.github_username
        self._api_calls = 0
        self._max_calls = getattr(config, "max_api_calls", MAX_API_CALLS_PER_RUN)

        self.session = _make_session(self.github_token, self.github_username)
        self.ai = AIClient(config)
        self._processed_files: set = self._load_history()

    # ── History ───────────────────────────────────────────────────────────────

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
        HISTORY_FILE.write_text(
            json.dumps({"processed_files": list(self._processed_files)}, indent=2)
        )

    def _mark_processed(self, repo_name: str, file_path: str):
        key = f"{repo_name}/{file_path}"
        self._processed_files.add(key)
        self._save_history()
        logger.debug(f"Marked processed: {key}")

    def _is_processed(self, repo_name: str, file_path: str) -> bool:
        return f"{repo_name}/{file_path}" in self._processed_files

    # ── Rate limiting ─────────────────────────────────────────────────────────

    def _check_rate_limit(self, resp: requests.Response) -> None:
        remaining = resp.headers.get("x-ratelimit-remaining")
        reset = resp.headers.get("x-ratelimit-reset")
        if remaining is not None and reset is not None:
            rem = int(remaining)
            logger.debug(f"GitHub rate limit remaining: {rem}")
            if rem < 10:
                wait = max(0, int(reset) - int(time.time())) + 5
                logger.warning(f"Rate limit nearly exhausted — sleeping {wait}s")
                time.sleep(wait)

    # ── HTTP helpers ──────────────────────────────────────────────────────────

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
            logger.error(f"Network error (GET {url}): {e}")
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
            logger.error(f"Network error (PUT {url}): {e}")
            return None

    # ── GitHub API calls ──────────────────────────────────────────────────────

    def get_user_repos(self) -> list[Repository]:
        url = f"{GITHUB_API_BASE}/user/repos?per_page=100&type=owner&sort=updated"
        resp = self._get(url)
        if resp is None or resp.status_code != 200:
            logger.error(
                f"Failed to fetch repos: {getattr(resp,'status_code','no response')}"
            )
            return []

        repos = []
        for r in resp.json():
            if r.get("fork", False) or r.get("archived", False):
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
        logger.info(f"Found {len(repos)} owned, non-archived repos")
        return repos

    def get_repo_files(
        self, repo_full_name: str, default_branch: str = "main"
    ) -> list[RepoFile]:
        # Only try the repo's actual default branch, then one fallback ("main" if different).
        # The old code tried up to 5 branches, wasting an API call per miss.
        branches_to_try = [default_branch]
        if default_branch not in ("main", "master"):
            branches_to_try.append("main")
        elif default_branch != "master":
            branches_to_try.append("master")

        resp = None
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

        _SKIP = {
            "node_modules",
            ".git",
            "__pycache__",
            "venv",
            ".venv",
            "dist",
            "build",
            "env",
            "egg-info",
            ".tox",
            "vendor",
            "site-packages",
            ".next",
            "target",
            "out",
        }

        files = []
        for item in data.get("tree", []):
            if not isinstance(item, dict) or item.get("type") != "blob":
                continue
            path = item.get("path", "")
            if not path:
                continue
            if set(Path(path).parts) & _SKIP:
                continue
            ext = Path(path).suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            size = item.get("size", 0)
            if size < 30 or size > MAX_FILE_CONTENT_LENGTH:
                continue
            files.append(
                RepoFile(
                    name=Path(path).name,
                    path=path,
                    sha=item.get("sha"),
                    size=size,
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
                content = base64.b64decode(data["content"]).decode(
                    "utf-8", errors="replace"
                )
                # Cache the SHA alongside content so push_contribution doesn't need
                # a second API call for the same endpoint.
                self._last_fetched_sha: dict[str, str] = getattr(
                    self, "_last_fetched_sha", {}
                )
                self._last_fetched_sha[f"{repo_full_name}/{file_path}"] = data.get(
                    "sha", ""
                )
                return content
            except Exception as e:
                logger.error(f"Failed to decode {file_path}: {e}")
        return None

    def get_file_sha(self, repo_full_name: str, file_path: str) -> Optional[str]:
        # Check in-memory cache first (populated by get_file_content) to avoid
        # making an extra API call for the same endpoint we just hit.
        cache = getattr(self, "_last_fetched_sha", {})
        cache_key = f"{repo_full_name}/{file_path}"
        if cache_key in cache:
            sha = cache[cache_key]
            if sha:
                logger.debug(f"SHA cache hit for {cache_key}")
                return sha
        # Cache miss — fetch from API
        url = f"{GITHUB_API_BASE}/repos/{repo_full_name}/contents/{file_path}"
        resp = self._get(url)
        if resp is not None and resp.status_code == 200:
            return resp.json().get("sha")
        return None

    # ── Target selection ──────────────────────────────────────────────────────

    def pick_contribution_target(
        self, repos: list[Repository]
    ) -> Optional[ContributionTarget]:
        """Select the best file to improve using a two-phase approach.

        Phase 1 (cheap): fetch each repo's git tree (1 API call/repo) and
        rank files using path/size heuristics — no content fetch needed.
        Scans at most MAX_REPOS_TO_SCAN repos per run to cap API usage.

        Phase 2 (targeted): fetch content only for top-ranked candidates.
        Total API calls: O(min(repos, MAX_REPOS_TO_SCAN)) + O(MAX_CONTENT_FETCHES).
        """
        import random

        MAX_REPOS_TO_SCAN = 5  # Don't scan every repo — stop after this many
        MAX_CONTENT_FETCHES = (
            3  # Phase 2 hard cap (was also 5, but fallback had no cap)
        )
        MAX_FALLBACK_FETCHES = 3  # Hard cap on the "first readable file" fallback loop

        repos_shuffled = list(repos)
        random.shuffle(repos_shuffled)
        repos_shuffled = repos_shuffled[:MAX_REPOS_TO_SCAN]  # Limit repos scanned

        PATH_BONUS = {
            "todo": 6,
            "fixme": 6,
            "hack": 4,
            "wip": 4,
            "temp": 3,
            "tmp": 3,
            "old": 2,
            "test": 1,
        }
        GOOD_SIZE_MIN = 200
        GOOD_SIZE_MAX = 3500

        shortlist: list[tuple[float, Repository, RepoFile]] = []

        for repo in repos_shuffled:
            files = self.get_repo_files(repo.full_name, repo.default_branch)
            if not files:
                continue
            for f in files:
                if self._is_processed(repo.full_name, f.path):
                    continue
                path_lower = f.path.lower()
                est = 0.0
                for kw, bonus in PATH_BONUS.items():
                    if kw in path_lower:
                        est += bonus
                if GOOD_SIZE_MIN <= f.size <= GOOD_SIZE_MAX:
                    est += 3
                else:
                    est -= 2
                if f.language == "Python":
                    est += 1
                shortlist.append((est, repo, f))

        if not shortlist:
            logger.info("No unprocessed files found — falling back to random pick")
            return self._random_pick(repos_shuffled)

        shortlist.sort(key=lambda x: x[0], reverse=True)

        # Phase 2: fetch content only for top candidates
        fetches = 0
        for est_score, repo, f in shortlist:
            if fetches >= MAX_CONTENT_FETCHES:
                break
            content = self.get_file_content(repo.full_name, f.path)
            fetches += 1
            if not content or len(content) < 80:
                continue
            score, reasons = _score_file(content, f.language)
            if score > 0:
                logger.info(
                    f"Selected: {repo.full_name}/{f.path} "
                    f"(score={score}, reasons={reasons})"
                )
                return ContributionTarget(
                    repo=repo, file=f, content=content, language=f.language
                )

        # Fallback: use first readable file — but with a hard cap to prevent runaway fetches
        logger.info(
            "No improvement signals in top candidates — using first readable file"
        )
        fallback_fetches = 0
        for _, repo, f in shortlist:
            if fallback_fetches >= MAX_FALLBACK_FETCHES:
                logger.info(
                    f"Fallback fetch cap ({MAX_FALLBACK_FETCHES}) reached — stopping"
                )
                break
            content = self.get_file_content(repo.full_name, f.path)
            fallback_fetches += 1
            if content and len(content) >= 80:
                return ContributionTarget(
                    repo=repo, file=f, content=content, language=f.language
                )

        return None

    def _random_pick(self, repos: list[Repository]) -> Optional[ContributionTarget]:
        import random

        repos = list(repos)
        random.shuffle(repos)
        MAX_CONTENT_FETCHES = 3  # Hard cap — don't scan every file in every repo
        fetches = 0
        for repo in repos:
            files = self.get_repo_files(repo.full_name, repo.default_branch)
            random.shuffle(files)
            for f in files:
                if fetches >= MAX_CONTENT_FETCHES:
                    return None
                if self._is_processed(repo.full_name, f.path):
                    continue
                content = self.get_file_content(repo.full_name, f.path)
                fetches += 1
                if content and len(content) > 80:
                    return ContributionTarget(
                        repo=repo, file=f, content=content, language=f.language
                    )
        return None

    # ── AI contribution generation ────────────────────────────────────────────

    def _build_prompt(self, target: ContributionTarget) -> str:
        content = target.content
        if len(content) > MAX_FILE_CONTENT_LENGTH:
            content = content[:MAX_FILE_CONTENT_LENGTH] + "\n... (file truncated)"

        repo_ctx = (
            f"\nRepository description: {target.repo.description}"
            if target.repo.description
            else ""
        )

        return f"""You are a careful open-source contributor making ONE small, genuine improvement.

File: {target.file.path}
Language: {target.language}{repo_ctx}

Pick the single most impactful improvement from:
- Fix or complete a TODO / FIXME comment
- Add a missing docstring or improve an existing one
- Fix a typo in a string, comment, or variable name
- Improve a vague variable name for clarity
- Add a missing type hint to a function signature
- Improve an error message to be more descriptive

Rules:
- Make ONLY ONE focused change — nothing more
- Do NOT change logic, algorithms, imports, or control flow
- Do NOT remove existing code unless it is a stray debug print
- Return the COMPLETE file content in improved_code, not just the changed part
- commit_message must follow conventional commits (fix:, docs:, refactor:, style:), max 72 chars

File content:
```
{content}
```

Respond with ONLY valid JSON — no preamble, no explanation, no markdown fences:
{{"improved_code": "...", "commit_message": "...", "description": "..."}}"""

    def generate_contribution(
        self, target: ContributionTarget
    ) -> tuple[Optional[Contribution], GenerateOutcome]:
        """
        Returns (contribution, outcome).

        outcome tells the caller WHY contribution is None:
          API_ERROR   → the AI provider is down/rate-limited — don't mark file processed
          NO_CHANGE   → AI reviewed the file and had nothing to do — mark processed
          PARSE_ERROR → AI response was garbled — mark processed and move on
        """
        prompt = self._build_prompt(target)

        try:
            raw = self.ai.complete_or_raise(prompt)
        except AIError as e:
            logger.error(
                f"AI API error for {target.file.path}: {e} "
                f"(provider={self.config.ai_provider})"
            )
            return None, GenerateOutcome.API_ERROR

        if not raw:
            return None, GenerateOutcome.API_ERROR

        result = _parse_ai_json(raw)
        if result is None:
            logger.error(
                f"Could not parse AI JSON for {target.file.path}. "
                f"Raw snippet: {raw[:200]}"
            )
            return None, GenerateOutcome.PARSE_ERROR

        required = ["improved_code", "commit_message", "description"]
        if not all(k in result for k in required):
            missing = [k for k in required if k not in result]
            logger.warning(f"AI response missing keys {missing} for {target.file.path}")
            return None, GenerateOutcome.PARSE_ERROR

        improved = result["improved_code"]
        if not isinstance(improved, str) or not improved.strip():
            logger.warning(f"AI returned empty improved_code for {target.file.path}")
            return None, GenerateOutcome.PARSE_ERROR

        if improved.strip() == target.content.strip():
            logger.info(f"AI made no changes to {target.file.path} — marking processed")
            return None, GenerateOutcome.NO_CHANGE

        contribution = Contribution(
            improved_code=improved,
            commit_message=str(result["commit_message"]).strip()[:72],
            description=str(result["description"]).strip(),
        )
        return contribution, GenerateOutcome.SUCCESS

    # ── Push ──────────────────────────────────────────────────────────────────

    def push_contribution(
        self, target: ContributionTarget, contribution: Contribution
    ) -> tuple[bool, Optional[str]]:
        repo_name = target.repo.full_name
        file_path = target.file.path

        sha = self.get_file_sha(repo_name, file_path)
        if not sha:
            logger.error("Could not get file SHA before push")
            return False, "Could not get file SHA"

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
            logger.info(
                f"✅ Pushed: {contribution.commit_message} → {repo_name}/{file_path}"
            )
            self._mark_processed(repo_name, file_path)
            return True, None

        status = getattr(resp, "status_code", "no response")
        body = getattr(resp, "text", "no body")[:300] if resp else "no response"

        if status == 403:
            # Almost always a token scope problem — give an actionable message.
            scope_hint = (
                "Push rejected (403 Forbidden) — your GitHub token lacks write access.\n"
                "Fix: GitHub → Settings → Developer settings → Personal access tokens\n"
                "  Classic token:       enable the 'repo' scope (full control of repos)\n"
                "  Fine-grained token:  set 'Contents' permission to 'Read and write'\n"
                "Then paste the new token in Agent Settings and try again."
            )
            logger.error(scope_hint)
            return False, scope_hint

        logger.error(f"Push failed: {status} — {body}")
        return False, f"HTTP {status}: {body}"

    # ── Validation ────────────────────────────────────────────────────────────

    def validate_credentials(self) -> tuple[bool, str]:
        url = f"{GITHUB_API_BASE}/user"
        resp = self._get(url)
        if resp is None:
            return False, "Network error — could not reach GitHub"
        if resp.status_code == 401:
            return False, "Invalid GitHub token (401 Unauthorized)"
        if resp.status_code == 403:
            return False, "Token lacks required permissions (needs 'repo' scope)"
        if resp.status_code != 200:
            return False, f"GitHub API error: {resp.status_code}"

        login = resp.json().get("login", "unknown")

        # Check that the token has write access by inspecting the OAuth scopes
        # header. Fine-grained tokens don't send this header — that's fine, we
        # can't pre-check them and will catch 403s at push time instead.
        scopes_header = resp.headers.get("X-OAuth-Scopes", "")
        if scopes_header:
            # Classic PAT: needs 'repo' (or 'public_repo' for public-only repos)
            granted = {s.strip() for s in scopes_header.split(",")}
            if "repo" not in granted and "public_repo" not in granted:
                return (
                    False,
                    f"Connected as {login}, but token is missing write scope.\n"
                    "Your classic PAT needs the 'repo' scope to push commits.\n"
                    "Go to GitHub → Settings → Developer settings → Personal access tokens\n"
                    "and regenerate with 'repo' checked.",
                )

        return True, f"Connected as: {login}"

    # ── Main entry ────────────────────────────────────────────────────────────

    def run(self) -> AgentResult:
        logger.info(
            f"Agent run started | provider={self.config.ai_provider} "
            f"model={self.config.effective_model()} "
            f"api_budget={self._max_calls} (calls so far: {self._api_calls})"
        )

        repos = self.get_user_repos()
        if not repos:
            return AgentResult(
                success=False,
                message="No repos found",
                error="Failed to fetch repos or no owned repos exist",
            )

        target = self.pick_contribution_target(repos)
        if not target:
            return AgentResult(
                success=False,
                message="No suitable contribution target found",
                error="All files either processed or no improvement signals found",
            )

        logger.info(
            f"Generating contribution for: {target.repo.full_name}/{target.file.path}"
        )
        contribution, outcome = self.generate_contribution(target)

        if contribution is None:
            if outcome == GenerateOutcome.API_ERROR:
                # ← KEY FIX: DO NOT mark the file processed — the API is the problem
                logger.warning(
                    f"AI API error for {target.file.path} — "
                    "file NOT marked processed (will retry next run)"
                )
                return AgentResult(
                    success=False,
                    message="AI API error — will retry this file next run",
                    error=f"AI provider ({self.config.ai_provider}) returned an error",
                )
            else:
                # NO_CHANGE or PARSE_ERROR — mark file processed, move on
                self._mark_processed(target.repo.full_name, target.file.path)
                return AgentResult(
                    success=False,
                    message="No improvement found for this file",
                    error=f"generate outcome: {outcome.name}",
                )

        return AgentResult(
            success=True,
            message="Contribution ready for review",
            job=ContributionJob(target=target, contribution=contribution),
        )

    def apply(self, job: ContributionJob) -> tuple[bool, Optional[str]]:
        return self.push_contribution(job.target, job.contribution)
