# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-04-07

### Added

- **Production-ready project structure**
  - `pyproject.toml` for modern Python packaging
  - `requirements-dev.txt` for development dependencies
  - `.gitignore` to protect sensitive files
  - `VERSION` file for version tracking

- **Enhanced Configuration System**
  - `AgentConfig` with Pydantic validation
  - Environment variable support (GITHUB_TOKEN, MISTRAL_API_KEY)
  - Config schema validation with helpful error messages
  - Settings GUI for runtime configuration

- **Improved Core Logic**
  - Type hints throughout `core.py`
  - Dataclasses for typed results (Repository, RepoFile, Contribution, etc.)
  - Better error handling and logging
  - Retry logic for network failures
  - GitHub API rate limit awareness

- **Settings Window**
  - GUI to configure interval, veto time, notifications
  - Test connection buttons for GitHub and Mistral
  - Save/cancel functionality

- **First-Run Onboarding Wizard**
  - Welcome screen with feature overview
  - Step-by-step GitHub token and Mistral key setup
  - Review screen before saving

- **Testing Infrastructure**
  - pytest configuration
  - Unit tests for `agent/config.py`
  - Unit tests for `agent/core.py`
  - Mock fixtures for GitHub and Mistral APIs

- **Logging Improvements**
  - Rotating log files (5MB max, 3 backups)
  - Separate error log tracking
  - Better log formatting

- **Additional File Type Support**
  - JavaScript (.js)
  - TypeScript (.ts)

### Changed

- Refactored `agent/core.py` with dataclasses
- Improved `tray/app.py` with better status management
- Updated `main.py` with improved logging and error handling
- Moved constants to `agent/constants.py`

### Fixed

- Proper Bearer token authentication (was incorrectly using different format)
- Network error handling for DNS failures
- Rate limit awareness and automatic backoff
