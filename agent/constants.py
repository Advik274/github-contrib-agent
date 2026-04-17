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

# ── AI Provider Registry ─────────────────────────────────────────────────────
# Each entry: (display_name, api_base, default_model, env_var, free_tier_note)
#
# OpenRouter free models use the ":free" suffix.
# The default model for each provider is verified working as of April 2026.
AI_PROVIDERS = {
    "google": (
        "Google AI Studio (Gemini)",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "gemini-2.0-flash",
        "GOOGLE_API_KEY",
        "Free: 15 req/min, 1M tokens/day",
    ),
    "openrouter": (
        "OpenRouter (multi-model)",
        "https://openrouter.ai/api/v1",
        "meta-llama/llama-3.2-3b-instruct:free",  # updated Apr 2026 — 3.1-8b removed from OpenRouter
        "OPENROUTER_API_KEY",
        "Free models available — append ':free' to model name",
    ),
    "groq": (
        "Groq (ultra-fast inference)",
        "https://api.groq.com/openai/v1",
        "llama-3.1-8b-instant",
        "GROQ_API_KEY",
        "Free: 6 000 req/day, fastest inference",
    ),
    "mistral": (
        "Mistral AI",
        "https://api.mistral.ai/v1",
        "mistral-small-latest",
        "MISTRAL_API_KEY",
        "Free tier: 1 req/s",
    ),
    "together": (
        "Together AI",
        "https://api.together.xyz/v1",
        "meta-llama/Llama-3-8b-chat-hf",
        "TOGETHER_API_KEY",
        "Free $25 credit on signup",
    ),
    "openai": (
        "OpenAI",
        "https://api.openai.com/v1",
        "gpt-4o-mini",
        "OPENAI_API_KEY",
        "Paid only",
    ),
}

# Ordered list for onboarding dropdown (best free options first)
AI_PROVIDER_ORDER = ["google", "openrouter", "groq", "mistral", "together", "openai"]

DEFAULT_AI_PROVIDER = "google"
AI_TIMEOUT = 60

MAX_API_CALLS_PER_RUN = 60  # GitHub allows 5000/hour for authenticated users; 60 gives headroom for repo scans
MAX_FILE_SIZE_BYTES = 500_000
MAX_FILE_CONTENT_LENGTH = 4000
MAX_RETRIES = 2  # Was 4 — each retry multiplies call cost
RETRY_BACKOFF_FACTOR = 1  # Was 2 — linear is safer under rate limits
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
    "paused": "#8b949e",
}

GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
GITHUB_USERNAME_ENV = "GITHUB_USERNAME"
