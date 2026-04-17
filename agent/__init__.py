# Lazy imports — don't import core at package level to avoid import errors
# when dependencies aren't installed yet (e.g. during setup).
from .config import AgentConfig, ConfigManager, get_config_manager, load_config

__all__ = [
    "AgentConfig",
    "ConfigManager",
    "get_config_manager",
    "load_config",
]
