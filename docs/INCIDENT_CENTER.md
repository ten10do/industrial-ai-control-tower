# Incident Center

Phase 6.9-C turns the incident lifecycle (6.9-B) into an operator-facing
**Incident Operations Center**: one place where correlated alarms, machine
diagnoses, and the human decision path into the existing approval flow are
visible together.

The center is **observation + decision support**. It is **not** an automation
executor: it never commands equipment, never bypasses approval, and never
creates a work order on its own.

## Purpose

| Capability | Where |
|---|---|
| Incident dashboard (header metrics + filterable table) | `GET /api/v1/incidents/dashboard`, frontend `/incidents` |
| Incident detail with alarms / diagnosis / asset / workflow / timeline | `GET /api/v1/incidents/{id}`, frontend `/incidents/:id` |
| Workflow bridge ("where does this incident stand?") | `GET /api/v1/incidents/{id}/workflow-context` |
| Enter the existing decision workflow | `POST /api/v1/incidents/{id}/start-workflow` |
| Operational metrics (MTTA / MTTR / alarm compression) | `GET /api/v1/incidents/metrics` |

## Architecture

```
Detection plane                     Response plane
────────────────                    ──────────────────────────────────────
Telemetry ──► Alarm rules           Incident (6.9-B lifecycle)
              │  (6.9-A)            │
              ▼                     ▼
          Alarm instances ──► Incident Center (dashboard/detail)
              │  (6.9-B       │
              │  correlation) ├─► Diagnosis context (read-only)
              │               ├─► Workflow context (bridge, read-only)
              ▼               └─► Start Workflow (gate → existing engine)
          Diagnosis                    │
                                       ▼
                            WorkflowRun (Phase 5 engine, untouched)
                                       │
                                       ▼
                              WAITING_APPROVAL  ◄── human decides
                                       │
                                       ▼
                          Approval ──► WorkOrder (existing flow)
```

Everything from `WorkflowRun` downward is the pre-existing Phase 5 engine.
Phase 6.9-C adds no graph node, no prompt, no policy rule, and no new entity:
the detail, bridge, and dashboard all read the existing `workflow_runs`,
`approvals`, `diagnoses`, and `audit_events` tables.

## The workflow gate

`POST /incidents/{id}/start-workflow` is guarded by
`IncidentWorkflowGate` (`app/incidents/operations.py`), which refuses with
**409 `INCIDENT_NOT_READY`** unless:

1. The incident status can legally reach the workflow-owned `UNDER_ANALYSIS`
   per the single transition table (`OPEN`, `ACKNOWLEDGED`, or
   `INVESTIGATING`).
2. A diagnosis exists (via the existing `diagnoses.incident_id` FK), carries a
   device, and is `FAULT` or `UNCERTAIN` — the same vocabulary the engine
   itself validates.

On pass, the endpoint delegates to the pre-existing `WorkflowService.start`,
which creates the `WorkflowRun` idempotently and runs the existing graph. The
run lands in `WAITING_APPROVAL` exactly as before. **No code path in the
Incident Center creates a work order or resumes an approval** — that happens
only through the existing human approval endpoints.

## Human-in-the-loop boundary

* The **system** correlates alarms, surfaces diagnoses, computes metrics, and
  **recommends** a plan (via the existing agent workflow).
* The **human** acknowledges, investigates, starts workflows, and — the only
  gate that matters — **approves or rejects** a plan. Approval buttons live on
  the existing approval pages and endpoints; the Incident Center only links to
  them and reports `approval_required` truthfully (true only while the latest
  run is `WAITING_APPROVAL` with a `PENDING` approval).
* No equipment control exists anywhere on this path.

## Metrics

| Metric | Formula |
|---|---|
| MTTA | mean(`acknowledged_at − created_at`) over acknowledged incidents |
| MTTR | mean(`resolved_at − created_at`) over resolved incidents |
| Alarm compression | linked alarms ÷ incidents (10 → ten alarms collapsed into one incident) |

## Files

* Backend: `app/incidents/operations.py` (services + gate),
  `app/api/incidents.py` (new routes), `app/incidents/contracts.py`
  (dashboard/bridge/metrics reads), `app/api/workflows.py` (detail now embeds
  the latest workflow summary additively).
* Frontend: `src/pages.tsx` (`IncidentsPage`, `IncidentDetailPage`),
  `src/api.ts`, `src/types.ts`, `src/incidentcenter.test.tsx`.
* Tests: `backend/tests/incidents/test_incident_operations.py` (20 tests,
  DB-backed).
