# Platform Reliability — Phase 6.10

## Purpose

Phase 6.10 lifts the platform from an operational prototype to a
**production-oriented industrial AI platform foundation**. It adds the
horizontal layers every production service needs — metrics, health,
recovery, and data-reliability guarantees — without changing any
decision logic.

What this phase is **not**: a 24/7 production deployment. There is no
Kubernetes, no cloud infrastructure, no autoscaling. The result is a
prototype hardened to be operable and observable.

## Architecture

```
Detection Plane                    Response Plane
────────────────                   ───────────────
Telemetry ──► Alarm ──► Diagnosis  Incident ──► Workflow ──► Approval ──► WorkOrder
     │            │          │         │           │            │
     └────────────┴──────────┴────┬────┴───────────┴────────────┘
                                  │
                     Platform Observability Layer (Phase 6.10)
                     ─────────────────────────────────────────
                     Metrics  │  Health  │  Recovery
                     (prometheus_client, /metrics)
```

- **Metrics** — every plane publishes counters/gauges/histograms to a single
  Prometheus exposition.
- **Health** — a lightweight liveness endpoint and a deep readiness endpoint.
- **Recovery** — bounded retry, MQTT reconnect tracking, supervised
  background tasks.
- **Data reliability** — duplicate/out-of-order ingestion guarantees and
  audit coverage of operator-critical actions.

The module lives in `backend/app/platform_observability/` and is fully
isolated from the existing Agent observability in `backend/app/observability/`
(which traces workflow runs and is untouched).

## Metrics (`GET /metrics`)

Prometheus exposition format, unauthenticated and unprefixed, per the scrape
convention. Active-count gauges are refreshed from the database at scrape
time; if the database is unreachable the gauges keep their last-known values
and the exposition still succeeds — a metrics endpoint that dies with the
database would hide every other signal exactly when it matters.

| Group | Metrics |
|---|---|
| Gateway | `adapter_connect_success_total`, `adapter_connect_failure_total`, `adapter_read_latency_seconds`, `adapter_last_success_timestamp` |
| Telemetry | `telemetry_ingest_total`, `telemetry_ingest_failed_total{reason}`, `telemetry_processing_latency_seconds{outcome}` |
| Alarm | `alarm_created_total`, `alarm_cleared_total`, `alarm_active_count` |
| Incident | `incident_created_total`, `incident_resolved_total`, `incident_active_count` |
| Workflow | `workflow_started_total`, `workflow_waiting_approval_total`, `workflow_failed_total` |
| Platform | `mqtt_reconnect_total`, `background_task_failure_total{task}` |

## Health & Readiness

- `GET /health` stays deliberately lightweight: `{"status": "ok"}` with no
  dependency checks — a load balancer needs liveness, not a database probe.
- `GET /ready` performs real dependency checks and returns structured state:

```json
{
  "status": "ready",
  "dependencies": {"postgres": "ok", "redis": "ok", "mqtt": "connected"},
  "checks": {
    "database": "ok",
    "redis": "ok",
    "mqtt": "connected",
    "model": "available"
  }
}
```

`status` is `ready` (HTTP 200) only when the hard dependencies (database,
redis, and any enabled feature store) are healthy. MQTT degradation is
visible in `checks.mqtt` but does not flip readiness by itself — losing MQTT
degrades the detection plane, it does not make the response plane unready.

## Failure Strategy

| Mechanism | Behaviour | Bound |
|---|---|---|
| Database retry (`AsyncRetry`) | Readiness probe tolerates transient blips | `max_attempts=3`, delays 1s/2s/4s; exhaustion raises `RetryExhaustedError` |
| Cancellation | `asyncio.CancelledError` is never retried | immediate propagation |
| MQTT recovery | existing automatic reconnect is preserved and now counted | `mqtt_reconnect_total` |
| Background tasks | every spawned task is wrapped by `monitor_background_task` | failures are logged (`background_task_failed`) and counted (`background_task_failure_total`), never silent |

## Data Reliability

Guarantees verified by the DB-backed tests in
`backend/tests/incidents/test_platform_reliability.py`:

- **Duplicate telemetry** — the same payload ingested twice produces one
  telemetry row and one alarm; the second ingest is counted as
  `DUPLICATE`. No duplicate incident or workflow can result.
- **Event ordering** — telemetry is always persisted, but the
  latest-only cache (`LatestTelemetryCache`, atomic stale-write Lua script)
  guarantees **latest timestamp wins**: an out-of-order reading never
  displaces the newest one and never re-triggers online diagnosis.
- **Repeated events** — a second acknowledge of the same alarm is rejected
  by the state machine and audited exactly once.
- **Audit coverage** — alarm acknowledge (`ALARM_ACKNOWLEDGED`), incident
  transitions (`INCIDENT_ACKNOWLEDGED`, …), and workflow start
  (`WORKFLOW_STARTED`, written before the graph runs, so the entry point is
  auditable even when the agent fails) each leave an audit row.

## Platform Metrics API

`GET /api/v1/platform/metrics` — operator-facing JSON summary:

```json
{
  "system": {"uptime_seconds": 100.0},
  "pipeline": {"telemetry_rate": 10.0},
  "incident": {"active": 5}
}
```

## Docker & Runtime

- Every long-running compose service (`postgres`, `redis`, `mosquitto`,
  `backend`, `frontend`) uses `restart: unless-stopped`, so an abnormal exit
  is recovered automatically by the Docker daemon.
- The frontend image has a `healthcheck` (HTTP probe against the local
  nginx); backend/postgres/redis/mqtt healthchecks are already defined.
- `.env.example` contains placeholder values only
  (`POSTGRES_PASSWORD=change-me-in-dotenv`, empty `MQTT_PASSWORD` /
  `AGENT_API_KEY`). No real token, password, or API key is committed.

## Production Boundary

Current state: **production-oriented prototype**. Observability, health,
bounded recovery, and data-reliability guarantees are in place. Not in
scope: 24/7 operation, Kubernetes, cloud deployment, horizontal scaling,
multi-region. The system **recommends**; humans **approve** — the
human-in-the-loop boundary is unchanged by this phase.
