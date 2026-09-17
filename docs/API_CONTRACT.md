# API Contract

## Namespace

All APIs are versioned under `/api/v1/`.

## Base URL

- Local development: `http://localhost:8000`
- Docker: `http://backend:8000`

## Authentication

Authentication is reserved for Phase 2+. Phase 0 endpoints are open.

## Health Endpoints

### GET /health

Returns service health status.

**Request**

```http
GET /health HTTP/1.1
Host: localhost:8000
```

**Response 200 OK**

```json
{
  "status": "ok"
}
```

### GET /ready

Returns `200` only when PostgreSQL and Redis are reachable and, when diagnosis is enabled, the
artifact is integrity-checked and loaded. MQTT is reported as `connected` or `degraded` but does
not by itself fail HTTP readiness. A missing, corrupt, or incompatible model reports diagnosis as
`unavailable`; telemetry ingestion remains isolated from that capability.

## Phase 2 Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/devices` | Register a device |
| GET | `/api/v1/devices?limit=100&offset=0` | List devices |
| GET | `/api/v1/devices/{device_id}` | Get by industrial ID |
| PATCH | `/api/v1/devices/{device_id}` | Update fields or lifecycle status |
| GET | `/api/v1/devices/{device_id}/telemetry` | Bounded history |
| GET | `/api/v1/devices/{device_id}/telemetry/latest` | Redis-first latest state |
| GET | `/api/v1/alarms` | List deterministic alarms |
| WS | `/ws/devices/{device_id}/telemetry` | Latest-value live telemetry |

## Phase 3 Diagnosis Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/devices/{device_id}/diagnoses?limit=100&cursor=...` | Cursor-paginated diagnosis history |
| GET | `/api/v1/devices/{device_id}/diagnoses/latest` | Latest persisted diagnosis |

Diagnosis statuses are `NORMAL`, `FAULT`, `UNCERTAIN`, and `FAILED`. Results include the telemetry
window, anomaly score, calibrated classifier confidence, severity, sensor evidence, model version,
feature version, trace ID, and creation time. `FAILED` is explicit and never converted to NORMAL.

Telemetry history accepts timezone-aware `start`, `end`, and exclusive `cursor` timestamps plus
`limit` from 1 to 500. It returns `{"items": [...], "next_cursor": ...}`. Device deletion is not
provided; use `INACTIVE` or `DECOMMISSIONED` to preserve history.

## Deferred Namespaces

The following namespaces remain later-phase work:

### /api/v1/incidents

- `GET /api/v1/incidents` — list incidents
- `GET /api/v1/incidents/{id}` — get incident
- `POST /api/v1/incidents` — create incident
- `PATCH /api/v1/incidents/{id}` — update incident status

### /api/v1/agent-runs

- `POST /api/v1/agent-runs` — start an agent run
- `GET /api/v1/agent-runs/{id}` — get run status and result

### /api/v1/approvals

- `GET /api/v1/approvals` — list pending approvals
- `GET /api/v1/approvals/{id}` — get approval
- `POST /api/v1/approvals/{id}/decision` — approve or reject

### /api/v1/work-orders

- `GET /api/v1/work-orders` — list work orders
- `GET /api/v1/work-orders/{id}` — get work order
- `POST /api/v1/work-orders` — create work order
- `PATCH /api/v1/work-orders/{id}` — update work order status

## Error Contract

All errors follow a consistent JSON structure:

```json
{
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "Device with id '123' not found.",
    "trace_id": "abc-123"
  }
}
```

Common status codes:

| Code | Meaning |
|------|---------|
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 422 | Validation Error |
| 500 | Internal Server Error |
| 503 | Service Unavailable |

Every HTTP response includes `X-Trace-ID`. A caller-supplied `X-Trace-ID` is propagated; otherwise
the backend creates one. MQTT ingestion creates a correlation ID per message.

## Status Values

Operations and agent runs use the unified status vocabulary:

```text
SUCCESS
FAILED
TIMEOUT
RETRYING
BLOCKED
NOT_RUN
INSUFFICIENT_EVIDENCE
REQUIRES_APPROVAL
REJECTED
```
