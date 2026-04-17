"""Tests for agent configuration."""
import json
import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from agent.config import AgentConfig, ConfigManager
from agent.constants import DEFAULT_INTERVAL_HOURS, DEFAULT_VETO_SECONDS, AI_PROVIDERS


@pytest.fixture
def valid_config():
    return {
        "github_token": "ghp_testtoken123",
        "ai_api_key": "test_ai_key",
        "github_username": "testuser",
        "interval_hours": DEFAULT_INTERVAL_HOURS,
        "veto_seconds": DEFAULT_VETO_SECONDS,
    }


class TestAgentConfig:
    def test_valid_config(self, valid_config):
        config = AgentConfig(**valid_config)
        assert config.github_token == "ghp_testtoken123"
        assert config.ai_api_key == "test_ai_key"
        assert config.github_username == "testuser"

    def test_default_values(self):
        config = AgentConfig(
            github_token="ghp_test",
            ai_api_key="key",
            github_username="user",
        )
        assert config.interval_hours == DEFAULT_INTERVAL_HOURS
        assert config.veto_seconds == DEFAULT_VETO_SECONDS
        assert config.auto_run_on_startup is True
        assert config.show_notifications is True
        assert config.ai_provider == "google"

    def test_custom_interval(self):
        config = AgentConfig(
            github_token="ghp_test",
            ai_api_key="key",
            github_username="user",
            interval_hours=8,
        )
        assert config.interval_hours == 8

    def test_custom_veto_time(self):
        config = AgentConfig(
            github_token="ghp_test",
            ai_api_key="key",
            github_username="user",
            veto_seconds=600,
        )
        assert config.veto_seconds == 600

    def test_interval_validation_low(self, valid_config):
        with pytest.raises(ValidationError):
            AgentConfig(**{**valid_config, "interval_hours": 0})

    def test_interval_validation_high(self, valid_config):
        with pytest.raises(ValidationError):
            AgentConfig(**{**valid_config, "interval_hours": 200})

    def test_veto_validation_low(self, valid_config):
        with pytest.raises(ValidationError):
            AgentConfig(**{**valid_config, "veto_seconds": 5})

    def test_veto_validation_high(self, valid_config):
        with pytest.raises(ValidationError):
            AgentConfig(**{**valid_config, "veto_seconds": 99999})

    def test_strip_whitespace(self, valid_config):
        config = AgentConfig(**{**valid_config, "github_token": "  ghp_test  "})
        assert config.github_token == "ghp_test"

    def test_provider_validation(self, valid_config):
        with pytest.raises(ValidationError):
            AgentConfig(**{**valid_config, "ai_provider": "nonexistent_provider"})

    def test_effective_model_default(self, valid_config):
        config = AgentConfig(**{**valid_config, "ai_provider": "groq", "ai_model": ""})
        assert config.effective_model() == AI_PROVIDERS["groq"][2]

    def test_effective_model_override(self, valid_config):
        config = AgentConfig(**{**valid_config, "ai_provider": "groq", "ai_model": "my-custom-model"})
        assert config.effective_model() == "my-custom-model"

    def test_legacy_migration(self):
        config = AgentConfig.from_legacy({
            "github_token": "ghp_test",
            "mistral_api_key": "old_key",
            "github_username": "user",
        })
        assert config.ai_api_key == "old_key"
        assert config.ai_provider == "mistral"

    def test_provider_api_base(self, valid_config):
        config = AgentConfig(**{**valid_config, "ai_provider": "google"})
        assert "generativelanguage" in config.provider_api_base()


class TestConfigManager:
    def test_save_and_load_config(self, tmp_path, valid_config):
        config_path = tmp_path / "config.json"
        with patch("agent.config.CONFIG_DIR", tmp_path):
            ConfigManager._instance = None
            ConfigManager._config = None
            manager = ConfigManager.__new__(ConfigManager)
            config = AgentConfig(**valid_config)
            manager.config_manager = manager
            with open(config_path, "w") as f:
                json.dump(config.model_dump(), f)
            loaded = json.loads(config_path.read_text())
            assert loaded["github_token"] == "ghp_testtoken123"
            assert loaded["ai_api_key"] == "test_ai_key"

    def test_env_var_override(self, tmp_path, valid_config):
        config_path = tmp_path / "config.json"
        with open(config_path, "w") as f:
            json.dump(valid_config, f)

        with patch("agent.config.CONFIG_DIR", tmp_path), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "env_github_token"}):
            ConfigManager._instance = None
            ConfigManager._config = None
            manager = ConfigManager()
            assert manager.config.github_token == "env_github_token"

        ConfigManager._instance = None
        ConfigManager._config = None

    def test_missing_required_field(self, tmp_path):
        config_path = tmp_path / "config.json"
        with open(config_path, "w") as f:
            json.dump({"github_token": "ghp_test"}, f)  # missing ai_api_key, github_username
        with patch("agent.config.CONFIG_DIR", tmp_path):
            ConfigManager._instance = None
            ConfigManager._config = None
            mgr = ConfigManager()  # construction is fine
            with pytest.raises(Exception):  # accessing .config should raise
                _ = mgr.config
        ConfigManager._instance = None
        ConfigManager._config = None
