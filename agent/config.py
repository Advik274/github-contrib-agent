import json
import logging
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .constants import (
    CONFIG_DIR,
    DEFAULT_INTERVAL_HOURS,
    DEFAULT_VETO_SECONDS,
    DEFAULT_AI_PROVIDER,
    GITHUB_TOKEN_ENV,
    GITHUB_USERNAME_ENV,
    MAX_VETO_SECONDS,
    MIN_VETO_SECONDS,
    AI_PROVIDERS,
)

logger = logging.getLogger(__name__)


class AgentConfig(BaseModel):
    github_token: str = Field(..., min_length=1, description="GitHub Personal Access Token")
    ai_provider: str = Field(default=DEFAULT_AI_PROVIDER, description="AI provider key")
    ai_api_key: str = Field(..., min_length=1, description="AI Provider API Key")
    ai_model: str = Field(default="", description="Model override (blank = provider default)")
    github_username: str = Field(..., min_length=1, description="GitHub username")
    interval_hours: int = Field(default=DEFAULT_INTERVAL_HOURS, ge=1, le=168)
    veto_seconds: int = Field(default=DEFAULT_VETO_SECONDS, ge=MIN_VETO_SECONDS, le=MAX_VETO_SECONDS)
    max_api_calls: int = Field(default=25, ge=1, le=200)
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR)$")
    auto_run_on_startup: bool = Field(default=True)
    show_notifications: bool = Field(default=True)

    @field_validator("github_token", "ai_api_key", "github_username")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()

    @field_validator("github_token")
    @classmethod
    def validate_github_token(cls, v: str) -> str:
        if not v.startswith(("ghp_", "github_pat_")):
            logger.warning("GitHub token doesn't look like a standard format (ghp_... or github_pat_...)")
        return v

    @field_validator("ai_provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        if v not in AI_PROVIDERS:
            raise ValueError(f"Unknown provider '{v}'. Valid: {list(AI_PROVIDERS.keys())}")
        return v

    def effective_model(self) -> str:
        if self.ai_model:
            return self.ai_model
        return AI_PROVIDERS[self.ai_provider][2]

    def provider_api_base(self) -> str:
        return AI_PROVIDERS[self.ai_provider][1]


class ConfigManager:
    _instance: Optional["ConfigManager"] = None
    _config: Optional[AgentConfig] = None

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if ConfigManager._config is None:
            ConfigManager._config = self._load_config()

    @property
    def config(self) -> AgentConfig:
        if ConfigManager._config is None:
            ConfigManager._config = self._load_config()
        return ConfigManager._config

    def _get_config_path(self) -> Path:
        return CONFIG_DIR / "config.json"

    def _config_exists(self) -> bool:
        return self._get_config_path().exists()

    def _load_config(self) -> AgentConfig:
        config_path = self._get_config_path()

        json_config: dict = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    json_config = json.load(f)
                logger.info(f"Loaded configuration from {config_path}")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in config file: {e}")
                raise ValueError(f"Invalid JSON in {config_path}: {e}")
            except Exception as e:
                logger.error(f"Failed to read config file: {e}")
                raise

        config_dict = self._merge_with_env_vars(json_config)
        return AgentConfig(**config_dict)

    def _merge_with_env_vars(self, json_config: dict) -> dict:
        merged = json_config.copy()

        if github_token := os.environ.get(GITHUB_TOKEN_ENV):
            merged["github_token"] = github_token
            logger.info(f"Using {GITHUB_TOKEN_ENV} from environment")

        if mistral_key := os.environ.get(MISTRAL_API_KEY_ENV):
            merged["mistral_api_key"] = mistral_key
            logger.info(f"Using {MISTRAL_API_KEY_ENV} from environment")

        if github_username := os.environ.get(GITHUB_USERNAME_ENV):
            merged["github_username"] = github_username
            logger.info(f"Using {GITHUB_USERNAME_ENV} from environment")

        return merged

    def reload(self) -> AgentConfig:
        ConfigManager._config = None
        return self.config

    def save(self, config: AgentConfig) -> None:
        config_path = self._get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)

        config_dict = config.model_dump(exclude_none=True)
        notes = {
            "_notes": {
                "github_token": "Create at https://github.com/settings/tokens — needs 'repo' scope",
                "mistral_api_key": "Get from https://console.mistral.ai/api-keys",
                "interval_hours": "How often the agent runs (1-168 hours)",
                "veto_seconds": f"Auto-push countdown ({MIN_VETO_SECONDS}-{MAX_VETO_SECONDS} seconds)",
                "max_api_calls": "Max GitHub API calls per run (1-100)",
                "log_level": "DEBUG, INFO, WARNING, or ERROR",
            }
        }

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({**config_dict, **notes}, f, indent=2)

        ConfigManager._config = config
        logger.info(f"Configuration saved to {config_path}")

    @staticmethod
    def create_example_config() -> Path:
        example_path = CONFIG_DIR / "config.example.json"
        example_content = {
            "github_token": "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN",
            "mistral_api_key": "YOUR_MISTRAL_API_KEY",
            "github_username": "your_github_username",
            "interval_hours": DEFAULT_INTERVAL_HOURS,
            "veto_seconds": DEFAULT_VETO_SECONDS,
            "max_api_calls": 30,
            "log_level": "INFO",
            "auto_run_on_startup": True,
            "show_notifications": True,
            "_notes": {
                "github_token": "Create at https://github.com/settings/tokens — needs 'repo' scope",
                "mistral_api_key": "Get from https://console.mistral.ai/api-keys",
                "interval_hours": "How often the agent runs (1-168 hours)",
                "veto_seconds": f"Auto-push countdown ({MIN_VETO_SECONDS}-{MAX_VETO_SECONDS} seconds)",
            },
        }

        with open(example_path, "w", encoding="utf-8") as f:
            json.dump(example_content, f, indent=2)

        return example_path


def load_config() -> AgentConfig:
    return ConfigManager().config


def get_config_manager() -> ConfigManager:
    return ConfigManager()
