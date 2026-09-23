# PHASE 6.9-C FINAL REPORT — Incident Center UI + Operational Workflow Integration

- **Date:** 2026-09-23
- **Base commit:** `e5f58e7` (Phase 6.9-B, on `main`)
- **Deliverable:** Incident Operations Center — dashboard UI, extended detail context, workflow bridge, gated workflow entry, operational metrics, documentation.
- **Boundary kept:** No LangGraph/prompt/policy/approval-rule/WorkOrder-state-machine/ML/RAG/Protocol-Adapter changes. No tag, no release, no Phase 7.

---

## 1. Implementation

### Backend

| Piece | Where |
|---|---|
| `IncidentOperationsService` — dashboard summary + bulk-resolved rows, workflow bridge, MTTA/MTTR/compression metrics (all read-only) | `app/incidents/operations.py` (new) |
| `IncidentWorkflowGate` — the single readiness check in front of workflow creation; `IncidentNotReadyError` = **409 `INCIDENT_NOT_READY`** with a machine-readable `reason` (`INCIDENT_STATUS` / `DIAGNOSIS`) | `app/incidents/operations.py` (new) |
| `IncidentDashboardItemRead` / `IncidentDashboardRead` / `IncidentWorkflowBridgeRead` / `IncidentMetricsRead` contracts | `app/incidents/contracts.py` (extended) |
| Dashboard / metrics / bridge / start-workflow routes | `app/api/incidents.py` (extended) |
| `GET /incidents/{id}` now embeds the newest workflow summary (`workflow` field, additive) | `app/api/workflows.py` + `app/workflow/contracts.py` (`IncidentDetailContextRead.workflow`) |

**API surface (new):**

| Route | Notes |
|---|---|
| `GET /api/v1/incidents/dashboard` | `summary` (`active`, `critical`, `unacknowledged`) counted over the whole population; `incidents` = newest page with bulk-resolved asset name + workflow status (3 extra queries total, never N+1) |
| `GET /api/v1/incidents/metrics` | `mtta_seconds` = mean(`acknowledged_at−created_at`); `mttr_seconds` = mean(`resolved_at−created_at`); `alarm_compression` = linked alarms ÷ incidents |
| `GET /api/v1/incidents/{id}/workflow-context` | `{incident_id, workflow_exists, workflow_run_id, workflow_status, approval_required}`; `approval_required` is true **only** while the latest run is `WAITING_APPROVAL` with a `PENDING` approval |
| `POST /api/v1/incidents/{id}/start-workflow` | gate → existing `WorkflowService.start`. Refusals: 404 unknown incident; **409 `INCIDENT_NOT_READY`** when the status cannot legally reach `UNDER_ANALYSIS` (allowed: `OPEN`, `ACKNOWLEDGED`, `INVESTIGATING`, derived from the transition table, not hardcoded) or when no `FAULT`/`UNCERTAIN` diagnosis with a device exists |

**No new migration and no new entity.** Everything reuses `incidents`, `diagnoses`, `workflow_runs`, `approvals`, `audit_events`, `incident_alarms`, `devices`, `asset_nodes`.

### Frontend

| Piece | Where |
|---|---|
| **Incident Center list** (`/incidents`): header metrics (Active Incident, Critical, Waiting Approval, Resolved Today), operational-metrics strip (MTTA / MTTR / alarm compression), table (Incident, Severity, Device, Asset, Status, Created, Last Alarm, Workflow) with status / severity / device filters | `src/pages.tsx` `IncidentsPage` |
| **Incident detail** (`/incidents/:id`): Overview (status, severity, priority, device, asset, action buttons Acknowledge / Start Investigation / Start Workflow / Resolve, waiting-approval notice), Alarm Timeline (numbered correlated alarm instances), Diagnosis Evidence (fault type, confidence, severity, timestamp — read-only, plus sensor evidence), existing workflow/evidence panels when a run exists | `src/pages.tsx` `IncidentDetailPage` |
| API client + types: `incidentDashboard`, `incidentMetrics`, `incidentWorkflowContext`, `acknowledgeIncident`, `startInvestigation`, `resolveIncident`, `startIncidentWorkflow`; `IncidentDashboard*`, `IncidentWorkflowBridge`, `IncidentMetrics` types; `IncidentDetail` extended with optional `alarms` / `device` / `asset` / `workflow` | `src/api.ts`, `src/types.ts` |
| Timeline styles | `src/styles.css` |

## 2. Workflow Integration — how the boundary holds

* `start-workflow` performs the readiness gate, writes **one** audit row
  (`INCIDENT_WORKFLOW_REQUESTED`), then delegates to the pre-existing
  `WorkflowService.start` — idempotent by its own key, runs the existing
  graph, lands in `WAITING_APPROVAL` via the existing interrupt.
* The Incident Center **cannot** resume an approval or create a work order:
  no such code exists in `operations.py` or the new routes. Work orders only
  ever appear through the existing approval endpoints, exactly as in Phase 5.
* `approval_required` is computed from persisted rows (`WAITING_APPROVAL` +
  `PENDING` approval), never asserted.

## 3. Tests

### Backend — `tests/incidents/test_incident_operations.py` (20 tests, DB-backed on one-shot PostgreSQL 16.15 @ 5433)

* Dashboard: summary counts over the whole population (active/critical/unacknowledged); bulk asset+workflow resolution; deviceless incidents tolerated; filters.
* Workflow bridge: no workflow → `workflow_exists:false`; `WAITING_APPROVAL` + `PENDING` approval → `approval_required:true`; decided approval → false.
* Start workflow: endpoint delegates `(incident_id, diagnosis_id, trace)` to the engine and returns the run; **409 without diagnosis** (`reason=DIAGNOSIS`); 404 unknown incident; gate status refusals (`MITIGATED`, unrecognised status); diagnosis-status/device refusals; entry-status set derived from the transition table (incl. `INVESTIGATING`).
* Metrics: exact MTTA (120 s), MTTR (3600 s), compression (2.0) from seeded timestamps; zeros on an empty database.

### Frontend — `src/incidentcenter.test.tsx` (6 tests)

List render (metrics + rows), severity filter, row → detail navigation, detail context display (overview / alarm timeline / diagnosis), lifecycle command dispatch (acknowledge), waiting-approval notice display.

## 4. Regression (all freshly executed)

| Suite | Command | Result |
|---|---|---|
| Backend incidents (DB-backed) | `pytest tests/incidents` | **203 passed** (183 from 6.9-B + 20 new) |
| Backend core | `pytest tests --ignore=tests/incidents --ignore=tests/assetconfig` | **195 passed, 1 skipped** |
| Backend assetconfig | `pytest tests/assetconfig` | **23 passed, 93 skipped** (DB opt-in, unchanged) |
| Frontend | `npm test` | **9 files passed** (35 tests incl. 6 new) |
| Frontend eslint | `npm run lint` | **exit 0** |
| Frontend build | `npm run build` | **vite build success** (dist emitted) |
| Simulator / ML | `pytest tests` | **24 passed / 16 passed** |
| ruff format + check | `ruff format backend/` / `ruff check backend/` | **All checks passed** (164 files) |
| mypy | `mypy app` | **Success, 104 source files** |

## 5. Migration

Phase 6.9-C adds **no migration** (additive API + UI only, reusing existing
tables). Per the validation contract, the existing chain was re-verified on
the one-shot PostgreSQL 16.15: `downgrade 08→07 → upgrade 07→08 → downgrade →
upgrade`, all four steps ran clean, seeded legacy row preserved with NULL new
columns. (Full-chain `alembic upgrade head` from an empty database still
requires pgvector via `20260920_03` — **`DOCKER_DAEMON_UNAVAILABLE`** stands as
in 6.9-B; no new migration impact was introduced by this phase.)

## 6. Git

- Branch `main`, base `e5f58e7`, working tree clean before the feature commit.
- Commit: **`feat: implement incident center and workflow integration`** — no tag, no release.
- New files: `app/incidents/operations.py`, `tests/incidents/test_incident_operations.py`, `frontend/src/incidentcenter.test.tsx`, `docs/INCIDENT_CENTER.md`, this report. Modified: `app/api/incidents.py`, `app/api/workflows.py`, `app/incidents/contracts.py`, `app/workflow/contracts.py`, `tests/incidents/conftest.py`, `frontend/src/{pages.tsx,api.ts,types.ts,styles.css}`.

## Final status: PHASE_6_9_C_COMPLETE
