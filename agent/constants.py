from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
LOG_DIR = PROJECT_ROOT / "logs"
DATA_DIR = PROJECT_ROOT / "data"
HISTORY_FILE = DATA_DIR / "contribution_history.json"

VERSION = (PROJECT_ROOT / "VERSION").read_text().strip()

SUPPORTED_EXTENSIONS = {
    ".py": "Python",
    ".java": "Java",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".md": "Markdown",
    ".txt": "Text",
}

CONTRIBUTION_TYPES = [
    "fix_todo",
    "improve_docstring",
    "add_readme_section",
    "fix_typo",
    "improve_comments",
    "add_type_hints",
    "improve_error_messages",
]

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
GITHUB_MEDIA_TYPE = "application/vnd.github+json"

MISTRAL_MODEL = "mistral-large-latest"
MISTRAL_TIMEOUT = 60

MAX_API_CALLS_PER_RUN = 30
MAX_FILE_SIZE_BYTES = 500_000
MAX_FILE_CONTENT_LENGTH = 4000
MAX_RETRIES = 4
RETRY_BACKOFF_FACTOR = 2
REQUEST_TIMEOUT = 15

DEFAULT_INTERVAL_HOURS = 4
DEFAULT_VETO_SECONDS = 300
MIN_VETO_SECONDS = 30
MAX_VETO_SECONDS = 3600

STATUS_COLORS = {
    "idle": "#2ea44f",
    "working": "#f0883e",
    "pushing": "#1f6feb",
    "pending": "#58a6ff",
    "error": "#f85149",
}

GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
MISTRAL_API_KEY_ENV = "MISTRAL_API_KEY"
GITHUB_USERNAME_ENV = "GITHUB_USERNAME"
