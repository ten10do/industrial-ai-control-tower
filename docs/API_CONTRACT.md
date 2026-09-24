# API Contract

## Namespace

All APIs are versioned under `/api/v1/`.

## Base URL

- Local development: `http://localhost:8000`
- Docker: `http://backend:8000`

## Authentication

Business mutation and read routes on the governed surface (incidents, workflows,
approvals, work orders, alarms, alarm rules, assets, device configuration,
connectivity, observability) require a bearer access token and declare the
permission they enforce; see `docs/SECURITY_MODEL.md` for the full matrix. A
missing credential is `401`, an identity without the permission is `403`. The
legacy `X-Actor` header is accepted as descriptive metadata only and never
decides attribution. `/health`, `/ready`, and the auth endpoints remain open.

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

Returns `200` only when PostgreSQL and Redis are reachable and each enabled diagnosis, knowledge,
and workflow capability initialized successfully. MQTT is reported as `connected` or `degraded`
but does not by itself fail HTTP readiness. A missing knowledge index or runtime-model credential
makes its enabled capability unavailable rather than silently selecting fabricated output.

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

## Phase 4 Knowledge Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/knowledge/search` | Free-text or structured deterministic evidence search |
| GET | `/api/v1/knowledge/documents?limit=100` | List persisted corpus metadata |
| GET | `/api/v1/knowledge/documents/{document_id}` | Get one document's provenance and hash |
| POST | `/api/v1/devices/{device_id}/knowledge-context` | Build a query from a persisted diagnosis and retrieve cited evidence |

Search accepts exactly one of `query` or `knowledge_query`, an optional exact-match filter object
(`equipment_type`, `document_type`, `model`, `revision`), `top_k` 1–20, and an optional pipeline:
`bm25`, `dense`, `hybrid`, or `hybrid_rerank`. The default is the frozen-evaluation-selected
`bm25` pipeline. Responses include the built query, corpus/embedding versions, retrieval run ID,
latency, cited evidence, and `SUFFICIENT`, `PARTIAL`, or `INSUFFICIENT_EVIDENCE` assessment.

Knowledge errors are explicit: `UNSUPPORTED_QUERY` (422), `CORPUS_NOT_AVAILABLE` (404),
`INDEX_NOT_AVAILABLE` (503), and `SEARCH_FAILED` (500). Every successful search is persisted as a
retrieval run.

## Phase 5 Workflow Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/incidents` | Bind a valid persisted diagnosis to an incident |
| GET | `/api/v1/incidents?status=...&limit=100` | List incidents with diagnosis and workflow lifecycle |
| GET | `/api/v1/incidents/{incident_id}` | Read incident and complete persisted diagnosis |
| POST | `/api/v1/incidents/{incident_id}/workflows` | Idempotently trigger the versioned workflow |
| GET | `/api/v1/workflows?status=...&limit=100` | List workflow summaries for operator views |
| GET | `/api/v1/workflows/{workflow_run_id}` | Read current typed state |
| GET | `/api/v1/workflows/{workflow_run_id}/trace` | Read workflow and agent audit summaries |
| POST | `/api/v1/workflows/{workflow_run_id}/cancel` | Safely cancel an allowed pre-terminal state |
| GET | `/api/v1/approvals/pending` | List pending human decisions |
| GET | `/api/v1/approvals/{approval_id}` | Read decision and bound plan version/hash |
| POST | `/api/v1/approvals/{approval_id}/approve` | Resume an interrupt and create a draft order |
| POST | `/api/v1/approvals/{approval_id}/reject` | Resume to rejection without a work order |
| GET | `/api/v1/work-orders/{work_order_id}` | Read a non-executing draft work order |
| GET | `/api/v1/work-orders?status=...&limit=100` | List draft work orders with approval audit context |
| GET | `/api/v1/workflow-metrics` | Read Phase 5 audit-derived counters and latency |

Approval decisions require `X-Development-Actor` and `{"reason":"..."}`. Repeating the same
decision is idempotent. Opposite concurrent decisions return `409 APPROVAL_ALREADY_DECIDED`; an
approval whose plan version/hash is stale returns `409 STALE_APPROVAL`.

Workflow terminal values are `BLOCKED`, `REJECTED`, `WORK_ORDER_CREATED`, `CANCELLED`, and
`FAILED`. `AUTO_ALLOWED` only permits deterministic creation of a `DRAFT` record. No endpoint in
Phase 5 executes maintenance or writes to industrial equipment.

Telemetry history accepts timezone-aware `start`, `end`, and exclusive `cursor` timestamps plus
`limit` from 1 to 500. It returns `{"items": [...], "next_cursor": ...}`. Device deletion is not
provided; use `INACTIVE` or `DECOMMISSIONED` to preserve history.

## Deferred Namespaces

The following namespaces remain later-phase work:

### /api/v1/agent-runs

- `POST /api/v1/agent-runs` — start an agent run
- `GET /api/v1/agent-runs/{id}` — get run status and result

Incident editing, agent-run mutation, work-order assignment/execution, and production identity/RBAC
remain deferred.

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
