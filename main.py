import logging
import logging.handlers
import sys
from pathlib import Path

from agent.config import ConfigManager, get_config_manager, load_config
from agent.constants import LOG_DIR, VERSION

LOG_DIR.mkdir(exist_ok=True)

log_handler = logging.handlers.RotatingFileHandler(
    LOG_DIR / "agent.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
log_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(log_handler)
root_logger.addHandler(logging.StreamHandler(sys.stdout))

logger = logging.getLogger(__name__)


def main():
    logger.info("=" * 60)
    logger.info(f"GitHub Contribution Agent v{VERSION.strip()} starting...")
    logger.info("=" * 60)

    try:
        config_manager = get_config_manager()
        config = config_manager.config
        logger.info(f"Loaded config for user: {config.github_username}")

        from tray.app import TrayApp
        app = TrayApp(config)
        app.start()

    except FileNotFoundError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Please copy config/config.example.json to config/config.json and fill it in.")
        sys.exit(1)
    except ValueError as e:
        logger.error(f"Configuration validation error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error during startup: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
