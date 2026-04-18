import json
from unittest.mock import patch

import pytest

from agent.config import AgentConfig, ConfigManager


@pytest.fixture
def temp_config_dir(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def valid_config():
    return {
        "github_token": "ghp_test123456789",
        "ai_api_key": "mistral_test_key",
        "github_username": "testuser",
        "interval_hours": 4,
        "veto_seconds": 300,
    }


class TestAgentConfig:
    def test_valid_config(self, valid_config):
        config = AgentConfig(**valid_config)
        assert config.github_token == "ghp_test123456789"
        assert config.github_username == "testuser"
        assert config.interval_hours == 4
        assert config.veto_seconds == 300

    def test_default_values(self):
        config = AgentConfig(
            github_token="ghp_test",
            ai_api_key="mistral_test",
            github_username="user",
        )
        assert config.interval_hours == 4
        assert config.veto_seconds == 300
        assert config.show_notifications is True
        assert config.auto_run_on_startup is True

    def test_custom_interval(self):
        config = AgentConfig(
            github_token="ghp_test",
            ai_api_key="mistral_test",
            github_username="user",
            interval_hours=8,
        )
        assert config.interval_hours == 8

    def test_custom_veto_time(self):
        config = AgentConfig(
            github_token="ghp_test",
            ai_api_key="mistral_test",
            github_username="user",
            veto_seconds=600,
        )
        assert config.veto_seconds == 600

    def test_interval_validation_low(self, valid_config):
        with pytest.raises(Exception):
            AgentConfig(**{**valid_config, "interval_hours": 0})

    def test_interval_validation_high(self, valid_config):
        with pytest.raises(Exception):
            AgentConfig(**{**valid_config, "interval_hours": 200})

    def test_veto_validation_low(self, valid_config):
        with pytest.raises(Exception):
            AgentConfig(**{**valid_config, "veto_seconds": 10})

    def test_veto_validation_high(self, valid_config):
        with pytest.raises(Exception):
            AgentConfig(**{**valid_config, "veto_seconds": 4000})

    def test_strip_whitespace(self, valid_config):
        config = AgentConfig(**{**valid_config, "github_token": "  ghp_test  "})
        assert config.github_token == "ghp_test"


class TestConfigManager:
    def test_save_and_load_config(self, temp_config_dir, valid_config):
        ConfigManager._config = None
        ConfigManager._instance = None

        config_path = temp_config_dir / "config.json"
        with open(config_path, "w") as f:
            json.dump(valid_config, f)

        from agent import config as config_module

        original_dir = config_module.CONFIG_DIR
        config_module.CONFIG_DIR = temp_config_dir

        try:
            manager = ConfigManager()
            config = manager.config

            assert config.github_token == valid_config["github_token"]
            assert config.github_username == valid_config["github_username"]
        finally:
            config_module.CONFIG_DIR = original_dir
            ConfigManager._config = None
            ConfigManager._instance = None

    def test_env_var_override(self, temp_config_dir, valid_config, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "env_ghp_token")
        monkeypatch.setenv("MISTRAL_API_KEY", "env_mistral_key")

        config_path = temp_config_dir / "config.json"
        with open(config_path, "w") as f:
            json.dump(valid_config, f)

        with patch("agent.config.CONFIG_DIR", temp_config_dir):
            ConfigManager._config = None
            ConfigManager._instance = None
            manager = ConfigManager()
            config = manager.config

            assert config.github_token == "env_ghp_token"
            assert config.ai_api_key == "env_mistral_key"

    def test_missing_required_field(self, temp_config_dir):
        invalid_config = {
            "github_token": "ghp_test",
            "ai_api_key": "mistral_test",
        }

        with patch("agent.config.CONFIG_DIR", temp_config_dir):
            ConfigManager._config = None
            ConfigManager._instance = None

            with pytest.raises(Exception):
                AgentConfig(**invalid_config)
