# Phase 6.10 Final Report — Platform Reliability Hardening

**Status**: PHASE_6_10_COMPLETE
**Base commit**: `c5d852f` (Phase 6.9-C) · **Branch**: main
**Constraint compliance**: no LangGraph / Prompt / Policy / Approval /
WorkOrder-state-machine / ML / RAG / Protocol-Adapter changes; no tag, no
release; stopped before Phase 7.

## 1. Platform Observability (6.10-A)

New isolated module `backend/app/platform_observability/` (the existing
Agent observability in `app/observability/` is untouched):

- `metrics.py` — prometheus_client definitions for all required metric
  families (gateway / telemetry / alarm / incident / workflow / platform).
- `GET /metrics` — Prometheus exposition, registered unprefixed in
  `app/main.py`. Active-count gauges (`alarm_active_count`,
  `incident_active_count`) are refreshed from the database at scrape time;
  if the database is unreachable the exposition still succeeds with
  last-known gauge values.
- Instrumentation hooks (additive, behaviour-preserving):
  - `services/telemetry.py`: decorator around `ingest_payload` counts
    ingests, failures by reason, and processing latency by outcome.
  - `incidents/service.py`: alarm created/cleared counters.
  - `incidents/incident_service.py` + `api/workflows.py`: incident
    created/resolved counters.
  - `workflow/service.py`: started / waiting-approval / failed counters.
  - `gateway/runtime.py`: adapter connect success/failure, read latency by
    result, last-success timestamp; gateway poll loop wrapped with
    `monitor_background_task`.
  - `infrastructure/mqtt/consumer.py`: `mqtt_reconnect_total`,
    consumer task supervised.
- Dependency added: `prometheus-client>=0.20` (backend/requirements.txt).

## 2. Health & Readiness (6.10-B)

- `GET /health` unchanged and lightweight (`{"status": "ok"}`).
- `GET /ready` restructured: deep probes with a **bounded retry** (3
  attempts, 1s/2s/4s) around the database probe, plus a new `checks` block:

```json
{"status": "ready|not_ready",
 "checks": {"database": "ok|unavailable", "redis": "ok|unavailable",
            "mqtt": "connected|degraded", "model": "available|missing|disabled"}}
```

MQTT degradation is visible but does not flip readiness by itself.

## 3. Failure Recovery (6.10-C)

- `platform_observability/resilience.py` — `AsyncRetry`: bounded
  (`max_attempts=3`, delays 1s/2s/4s), retry-list-scoped
  (`asyncio.CancelledError` and non-declared exceptions propagate
  immediately), injectable sleep for tests. `default_database_retry()` is
  the phase policy; used by the readiness probe.
- MQTT reconnect counter added on the existing reconnect path.
- `platform_observability/tasks.py` — `monitor_background_task`: every
  asyncio background task (gateway devices, MQTT consumer) is supervised;
  unexpected exits are logged (`background_task_failed`) and counted
  (`background_task_failure_total{task}`), never silent.

## 4. Data Reliability (6.10-D)

Verified by DB-backed tests (one-shot PostgreSQL):

- **Duplicate telemetry**: same payload twice → one telemetry row, one
  alarm, second ingest `DUPLICATE`; zero duplicate incidents/workflows.
- **Out-of-order telemetry**: both readings persist; the atomic
  latest-only cache keeps the **newest** timestamp (latest wins, not
  last-written), and stale readings never re-trigger diagnosis.
- **Repeated event**: double acknowledge → state machine rejects the
  second; exactly one `ALARM_ACKNOWLEDGED` audit row.
- **Audit coverage**: alarm acknowledge, incident transition, and workflow
  start each leave audit rows. `WORKFLOW_STARTED` is written **before** the
  graph runs — the human-decision entry point is auditable even when the
  agent fails (test verifies the row survives a graph crash, workflow run
  then FAILED).

## 5. Platform Metrics API (6.10-E)

`GET /api/v1/platform/metrics` (also mounted at `/api/platform/metrics`):

```json
{"system": {"uptime_seconds": 100.0},
 "pipeline": {"telemetry_rate": 10.0},
 "incident": {"active": 7}}
```

## 6. Docker & Runtime (6.10-F)

- `docker-compose.yml`: `restart: unless-stopped` on postgres, redis,
  mosquitto, backend, frontend; frontend healthcheck (HTTP probe via wget)
  added. Backend/DB/Redis/MQTT healthchecks already existed.
- `.env.example` audited: placeholders only
  (`POSTGRES_PASSWORD=change-me-in-dotenv`, empty `MQTT_PASSWORD`,
  empty `AGENT_API_KEY`). No real secrets committed.
- **`DOCKER_DAEMON_UNAVAILABLE`**: Docker Desktop is installed but the
  daemon is not running (`docker info` exit 1), so compose healthcheck /
  restart behaviour could not be exercised live. Configuration was verified
  statically. The full-chain `alembic check` remains blocked by the same
  limitation as 6.9-B/6.9-C (pgvector required by migration `20260920_03`,
  one-shot PostgreSQL has no pgvector); targeted migration verification is
  provided instead.

## 7. Tests

New files:

- `backend/tests/test_platform_reliability.py` (14 tests, no DB):
  health stays lightweight; ready reports database/redis unavailable (503)
  and mqtt degraded (200); retry success after transient failures with
  recorded delays `[1s, 2s]`; retry exhaustion raises `RetryExhaustedError`
  after 3 attempts; non-retryable exceptions propagate immediately;
  default policy matches the phase spec (3 / 1s/2s/4s); failing background
  task increments the failure counter; `/metrics` returns 200 with
  Prometheus content-type and every required metric name, and survives
  database failure; `/api/v1/platform/metrics` shape (uptime / rate /
  active); readiness probe retries a transient database blip (3 calls) and
  recovers.
- `backend/tests/incidents/test_platform_reliability.py` (6 tests,
  DB-backed): the data-reliability guarantees of §4.
- `tests/incidents/conftest.py`: table schema extended with
  `retrieval_runs` (workflow-start audit test reaches the real
  `WorkflowService.start` up to the fake graph).

## 8. Validation Results (all executed this session)

| Suite | Result |
|---|---|
| backend tests/incidents (DB-backed, PostgreSQL 16.15 @5433) | **209 passed** (183 of 6.9-B + 20 of 6.9-C + 6 new) |
| backend core + assetconfig (`--ignore=tests/incidents`) | **232 passed, 94 skipped** (incl. 14 new platform tests) |
| ruff format / ruff check | **clean** (171 files) |
| mypy | **Success, 109 source files** |
| frontend `npm test` / `npm run lint` / `npm run build` | **exit 0 / exit 0 / exit 0** (9 test files) |
| migration chain | `downgrade 08→07` → `upgrade 07→08` → current `20260923_08 (head)` re-verified on the seed database |
| Docker | **`DOCKER_DAEMON_UNAVAILABLE`** (daemon not running; compose config verified statically only) |

## 9. Git

- Commit: `feat: add platform reliability hardening` on main, based on
  `c5d852f`. No tag, no release.
- New files: `app/platform_observability/{__init__,metrics,tasks,resilience}.py`,
  `app/api/platform.py`, 2 test files, `docs/PLATFORM_RELIABILITY.md`, this report.
- Modified: `app/main.py`, `app/services/telemetry.py`,
  `app/incidents/service.py`, `app/incidents/incident_service.py`,
  `app/workflow/service.py`, `app/api/workflows.py`,
  `app/gateway/runtime.py`, `app/infrastructure/mqtt/consumer.py`,
  `tests/incidents/conftest.py`, `docker-compose.yml`,
  `backend/requirements.txt`.

## 10. Boundary Statement

Incident Center decision logic, workflow graph, prompts, safety policy,
approval rules, and the WorkOrder state machine are untouched — the
hardening layer only observes, reports, and recovers. The system
recommends; humans approve.
