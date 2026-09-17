# Industrial AI Control Tower — Backend

FastAPI backend and telemetry data platform for Phase 2.

## Development Setup

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements-dev.txt
```

## Run

```bash
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The service consumes `industrial/devices/+/telemetry`. PostgreSQL is the system of record;
Redis stores only `device:{device_id}:latest`. Configure all connections with the root
`.env.example` values.

Register a device before publishing its telemetry:

```bash
curl -X POST http://localhost:8000/api/v1/devices \
  -H "Content-Type: application/json" \
  -d '{"device_id":"MOTOR-001","device_type":"IndustrialMotor","name":"Demo motor"}'
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

See `../docs/DATA_PLATFORM.md`, `../docs/INGESTION_PIPELINE.md`, and
`../docs/API_CONTRACT.md` for consistency and delivery semantics.
