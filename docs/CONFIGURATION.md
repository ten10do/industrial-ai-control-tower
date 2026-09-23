# Configuration Management

## Principles

- `.env.example` is the **template of record**. It contains placeholders
  only — never a real password, token, API key, or private endpoint. This is
  enforced by `scripts/validate_env.py --mode example` in CI.
- Real values live in `.env` (git-ignored). **Secrets are injected from
  outside the repository** — from the operator's secret store, a vault, or
  direct `.env` editing on the target host. Nothing secret is committed.
- A placeholder left unchanged in a runtime `.env` (e.g.
  `POSTGRES_PASSWORD=change-me-in-dotenv`) is a hard configuration error and
  fails validation.

Validate any env file before use:

```bash
python scripts/validate_env.py .env.example --mode example   # template scan
python scripts/validate_env.py .env --mode runtime           # runtime config
```

## Configuration Categories

### Database (PostgreSQL)

| Variable | Purpose |
|---|---|
| `POSTGRES_HOST` / `POSTGRES_PORT` | Server coordinates for tooling |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | Credentials — **secret** |
| `POSTGRES_DB` | Database name |
| `DATABASE_URL` | Full asyncpg URL used by the backend and Alembic |

### Redis

| Variable | Purpose |
|---|---|
| `REDIS_HOST` / `REDIS_PORT` | Server coordinates for tooling |
| `REDIS_URL` | URL used by the latest-telemetry cache |

### MQTT

| Variable | Purpose |
|---|---|
| `MQTT_HOST` / `MQTT_PORT` | Broker address used by the consumer |
| `MQTT_USERNAME` | Optional; empty enables anonymous mode (matches the bundled broker) |
| `MQTT_PASSWORD` | Optional **secret**; may stay empty for anonymous brokers |
| `MQTT_ENABLED` | Feature flag |

### LLM / Agent (workflow runtime)

| Variable | Purpose |
|---|---|
| `WORKFLOW_ENABLED` | Master flag; `false` in the default deployment |
| `AGENT_PROVIDER` | Provider adapter (`openai_compatible`; `test` is CI-only) |
| `AGENT_MODEL` | Model name — required when the workflow is enabled |
| `AGENT_API_KEY` | **Secret**, injected externally; never committed |
| `AGENT_BASE_URL` | Provider endpoint (public by default; a private endpoint would belong in `.env`, not the template) |
| `AGENT_TEMPERATURE`, `AGENT_TIMEOUT_SECONDS`, `AGENT_MAX_ATTEMPTS`, `AGENT_BACKOFF_SECONDS`, `AGENT_SCHEMA_MAX_ATTEMPTS` | Deterministic runtime tuning |

### Diagnosis / Knowledge artifacts

| Variable | Purpose |
|---|---|
| `DIAGNOSIS_ENABLED`, `DIAGNOSIS_ARTIFACT_PATH`, `DIAGNOSIS_MANIFEST_PATH` | ML artifact wiring |
| `KNOWLEDGE_ENABLED`, `KNOWLEDGE_INDEX_PATH`, `KNOWLEDGE_CORPUS_VERSION`, `KNOWLEDGE_EMBEDDING_VERSION` | RAG-index wiring (built-in corpus; no external service) |

### Observability

| Variable | Purpose |
|---|---|
| `LOG_LEVEL` | Backend log level (`DEBUG`…`CRITICAL`) |
| `PROMETHEUS_PORT` | Reserved for a future Prometheus server |

`GET /metrics` and `GET /api/v1/platform/metrics` (Phase 6.10) need no
configuration beyond the backend port.

## Validation Rules

| Mode | Rejects |
|---|---|
| `example` | Real-looking secrets (anything non-empty that is not `change-me`, `<placeholder>`, or `${...}` expansion); missing required keys |
| `runtime` | Missing or empty required keys; unchanged placeholders for `POSTGRES_PASSWORD`; empty `POSTGRES_PASSWORD`; non-integer or out-of-range ports/timeouts; invalid `LOG_LEVEL` |

Secrets that may legitimately stay empty (`MQTT_PASSWORD` for an anonymous
broker, `AGENT_API_KEY` while `WORKFLOW_ENABLED=false`) are documented here
and allowed by `runtime` mode.
