# Industrial AI Control Tower — Backend

FastAPI backend skeleton for Phase 0.

## Development Setup

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements-dev.txt
```

## Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Test

```bash
pytest
```

## Lint

```bash
ruff check .
ruff format --check .
```

## Type Check

```bash
mypy app tests
```
