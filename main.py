import logging
import logging.handlers
import signal
import sys

from agent.constants import LOG_DIR, VERSION

LOG_DIR.mkdir(exist_ok=True)

log_handler = logging.handlers.RotatingFileHandler(
    LOG_DIR / "agent.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(log_handler)
root_logger.addHandler(logging.StreamHandler(sys.stdout))

logger = logging.getLogger(__name__)

_tray_app = None


def signal_handler(signum, frame):
    logger.info("Shutdown signal received — exiting...")
    if _tray_app:
        try:
            _tray_app._hibernate_agent()
            if _tray_app.icon:
                _tray_app.icon.stop()
        except Exception:
            pass
    sys.exit(0)


def main():
    global _tray_app

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("=" * 60)
    logger.info(f"GitHub Contribution Agent v{VERSION.strip()} starting...")
    logger.info("=" * 60)

    # ── Check for first-run onboarding ────────────────────────────────────────
    from agent.constants import CONFIG_DIR
    config_path = CONFIG_DIR / "config.json"

    if not config_path.exists():
        logger.info("No config found — launching setup wizard")
        from tray.onboarding import OnboardingWizard
        wizard = OnboardingWizard()
        wizard.show()
        # After onboarding, the wizard starts TrayApp internally and calls mainloop.
        # We exit here so we don't double-start.
        return

    # ── Normal startup ────────────────────────────────────────────────────────
    try:
        from agent.config import get_config_manager
        config_manager = get_config_manager()
        config = config_manager.config
        logger.info(f"Loaded config | user={config.github_username} "
                    f"provider={config.ai_provider} model={config.effective_model()}")

        from tray.app import TrayApp
        _tray_app = TrayApp(config)
        _tray_app.start()

        # Tk mainloop — blocks until quit
        _tray_app._root.mainloop()

    except FileNotFoundError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except ValueError as e:
        logger.error(f"Configuration validation error: {e}")
        # Bad config → re-run onboarding
        logger.info("Launching setup wizard to fix configuration...")
        from tray.onboarding import OnboardingWizard
        OnboardingWizard().show()
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
