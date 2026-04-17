# Agent Commands

This file contains commands for linting, testing, typechecking, and building the project.

## Development Commands

### Install Dependencies

```bash
# Install runtime dependencies
pip install -r requirements.txt

# Install development dependencies (linting, testing, typechecking)
pip install -r requirements-dev.txt
```

### Run Tests

```bash
# Run all tests with pytest
pytest
```

### Code Formatting

```bash
# Auto-format Python code using Black
black .

# Sort Python imports using isort
isort .
```

### Type Checking

```bash
# Run static type checking on the agent module
mypy agent/
```

### Linting

```bash
# Run Ruff linter to catch code issues
ruff check .
```

### Full Quality Check

```bash
# Run all quality checks in sequence (formatting, linting, type checking, tests)
black . && isort . && ruff check . && mypy agent/ && pytest
```

## Building

### Standalone Windows Executable

```bat
# Build standalone exe (no Python needed on target machine)
build_exe.bat

# Or use the installer which also builds
install.bat
```

The standalone exe will be in `dist\github_agent\github_agent.exe`.

### Python Package

```bash
# Build the package for distribution (requires build package)
pip install build
python -m build
```
