# Agent Commands

This file contains commands for linting, testing, and typechecking the project.

## Development Commands

### Install Dependencies

```bash
# Runtime dependencies
pip install -r requirements.txt

# Development dependencies
pip install -r requirements-dev.txt
```

### Run Tests

```bash
pytest
```

### Code Formatting

```bash
# Format all Python files
black .

# Sort imports
isort .
```

### Type Checking

```bash
mypy agent/
```

### Linting

```bash
ruff check .
```

### Full Quality Check

```bash
# Run all checks
black . && isort . && ruff check . && mypy agent/ && pytest
```

## Building

```bash
# Build package (when ready for distribution)
pip install build
python -m build
```
