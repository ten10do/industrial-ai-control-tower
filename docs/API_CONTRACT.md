# API Contract

## Namespace

All APIs are versioned under `/api/v1/`.

## Base URL

- Local development: `http://localhost:8000`
- Docker: `http://backend:8000`

## Authentication

Authentication is reserved for Phase 2+. Phase 0 endpoints are open.

## Phase 0 Endpoints

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

## Future Namespaces

The following namespaces are planned but not implemented in Phase 0:

### /api/v1/devices

- `GET /api/v1/devices` — list devices
- `GET /api/v1/devices/{id}` — get device
- `POST /api/v1/devices` — register device
- `PUT /api/v1/devices/{id}` — update device

### /api/v1/telemetry

- `POST /api/v1/telemetry` — ingest telemetry batch
- `GET /api/v1/telemetry` — query telemetry

### /api/v1/alarms

- `GET /api/v1/alarms` — list alarms
- `GET /api/v1/alarms/{id}` — get alarm
- `PATCH /api/v1/alarms/{id}` — acknowledge or clear alarm

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
