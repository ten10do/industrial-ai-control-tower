# Control Tower UI

## Routes

| Route | Operational purpose | Data source |
|---|---|---|
| `/` | Fleet counts, live motor summary, recent incidents, approvals, workflows | Real REST APIs |
| `/devices` | Searchable/filterable equipment registry and latest state | Devices + latest telemetry |
| `/devices/:deviceId` | Historical trends, live WebSocket, alarms, latest diagnosis | REST + WebSocket |
| `/incidents` | Incident, diagnosis, severity, and workflow lifecycle | Incident query API |
| `/incidents/:incidentId` | Diagnosis → sensor → knowledge → Agent → policy explanation chain | Incident, workflow, trace, corpus APIs |
| `/workflows/:workflowRunId` | Structured Agent trace and deterministic decision | Workflow trace API |
| `/approvals` | Pending plans with device, fault, severity, and risk | Approval + workflow APIs |
| `/approvals/:approvalId` | Full decision context and real Approve/Reject mutation | Approval APIs |
| `/work-orders` | Real non-executing maintenance plans | Work-order query API |
| `/work-orders/:workOrderId` | Plan, grounding, safety requirements, approval audit | Work-order detail API |

## Operator semantics

Status always includes a text label and a shape in addition to color. `Alarm` is presented as a
deterministic event and never relabeled as a diagnosis. The latest ML result includes classification,
confidence, anomaly score, severity, model/feature versions, window, and sensor deviations.

Knowledge citations use `Document → Page → Section`. Selecting a citation opens provenance,
revision, source type, and the exact escaped excerpt. Local filesystem paths are never linked.

Approval requires an operator identity and a reason of at least three characters. Both buttons
enter `SUBMITTING` together after the first click. A successful approval navigates to the created
work order; rejection remains terminal without inventing a work order. Backend concurrency and
idempotency remain authoritative.

Work-order pages explicitly state that a `DRAFT` is planned work and is not evidence of physical
execution, repair, resolution, or completion.

## Configuration

The production image uses same-origin defaults through Nginx:

- `/api` → Backend REST
- `/ws` → Backend WebSocket with upgrade headers
- `/health` and `/ready` → Backend status

For local cross-origin development only, set public locations such as:

```text
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_BASE_URL=ws://localhost:8000
```

Never store an API key or credential in a `VITE_*` variable.
