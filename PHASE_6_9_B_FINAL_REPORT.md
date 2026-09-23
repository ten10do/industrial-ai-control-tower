# PHASE 6.9-B FINAL REPORT — Incident Lifecycle & Correlation Engine

- **Date:** 2026-09-23
- **Base commit:** `112d879` (Phase 6.9-A, on `main`, local `main == origin/main`)
- **Scope:** Incident lifecycle state machine + services + API; Alarm→Incident correlation engine; diagnosis association; read-only incident context; migration `20260923_08`; tests; docs.
- **Out of scope (untouched):** Frontend UI, Agent Workflow, LangGraph, Prompt, Safety Policy, WorkOrder lifecycle, ML, RAG, Protocol Gateway, Release/Tag, Phase 6.9-C.

---

## 1. Implementation

### 1.1 State machine — single source of truth

`backend/app/incidents/states.py` now owns the full authority for incident status:

- `IncidentStatus` (StrEnum, 11 values): `OPEN, ACKNOWLEDGED, INVESTIGATING, UNDER_ANALYSIS, ACTION_PENDING, WORK_ORDER_CREATED, MITIGATED, RESOLVED, CLOSED, REOPENED, CANCELLED`
- `INCIDENT_TRANSITIONS` — one dict, all legal edges:

| From | Allowed to |
|---|---|
| `OPEN` | `ACKNOWLEDGED`, `CANCELLED`, `UNDER_ANALYSIS` |
| `ACKNOWLEDGED` | `INVESTIGATING`, `CANCELLED`, `UNDER_ANALYSIS` |
| `INVESTIGATING` | `MITIGATED`, `UNDER_ANALYSIS` |
| `UNDER_ANALYSIS` | `ACTION_PENDING`, `MITIGATED` |
| `ACTION_PENDING` | `WORK_ORDER_CREATED` |
| `WORK_ORDER_CREATED` | `MITIGATED` |
| `MITIGATED` | `RESOLVED` |
| `RESOLVED` | `CLOSED` |
| `CLOSED` | `REOPENED` |
| `REOPENED` | `INVESTIGATING` |
| `CANCELLED` | nothing |

- `CLOSED` has exactly one exit (explicit `reopen_incident`); `CANCELLED` is dead by decision and nothing leaves it. Forbidden moves `CLOSED → INVESTIGATING` and `CANCELLED → OPEN` are refused with `INCIDENT_STATE_INVALID` (HTTP 409).
- Workflow-owned statuses (`UNDER_ANALYSIS`, `ACTION_PENDING`, `WORK_ORDER_CREATED`) are present in the table so no transition is unrepresentable, but no DB CHECK constraint was added — the transition table in `states.py` is the single enforced authority (documented in the migration docstring).
- Helpers: `is_incident_transition_allowed`, `describe_incident_transitions`, `as_incident_status`, plus `OPEN_INCIDENT_STATUSES` / `TERMINAL_INCIDENT_STATUSES`.

### 1.2 Services (`backend/app/incidents/incident_service.py`)

- **`IncidentLifecycleService`** — `acknowledge_incident` (records `acknowledged_at`/`acknowledged_by`), `start_investigation`, `resolve_incident` (`resolved_at`), `close_incident` (`closed_at`), `reopen_incident` (clears `resolved_at`/`closed_at`). Every command validates the move against `INCIDENT_TRANSITIONS`, stamps the actor, and writes exactly one audit row per state change. Errors: `IncidentNotFoundError` (404), `IncidentStateError` / `INCIDENT_STATE_INVALID` (409, payload names current status and legal targets).
- **`IncidentCorrelationService`** — deterministic Device + Time Window correlation, `DEFAULT_CORRELATION_WINDOW_SECONDS = 600` (10 min), anchored on `incident.last_alarm_at` (activity clock = `coalesce(last_alarm_at, created_at)`). No ML / embedding / LLM. Merging escalates severity/priority when the incoming alarm is higher (`SEVERITY_PRIORITY`: CRITICAL→URGENT, MAJOR→HIGH, WARNING→MEDIUM, MINOR/INFO→LOW). `attach_alarm_to_incident` is idempotent (unique pair + `on_conflict_do_nothing`) and raises `AlarmIncidentMismatchError` on cross-device attach. Resolved/closed/cancelled incidents never absorb new alarms.
- **`IncidentContextService`** — read-only `build_context(incident_id)` returning incident + linked alarms + device + asset + latest diagnosis + audit timeline (oldest first).

### 1.3 Diagnosis association — design choice

**Reused the existing `diagnoses.incident_id` FK (one-to-many); no new link table.** Rationale: the Phase 6.x diagnosis flow already writes `incident_id` when a diagnosis completes; a second association path would create two competing sources of truth. `IncidentContextService.latest_diagnosis` reads the most recent diagnosis for the incident through this existing FK. (Alternative considered: `incident.diagnosis_id` column — rejected because it inverts the existing ownership and requires backfill.)

### 1.4 API (`backend/app/api/incidents.py`, registered under both `/api/v1` and `/api`)

- `GET  /incidents` — list with `status` / `severity` / `device_id` filters (also surfaced in `workflows.py` list)
- `GET  /incidents/{id}` — full context bundle (additive-only: `IncidentDetailRead` fields unchanged; new fields live in `IncidentDetailContextRead`, frontend-compatible)
- `POST /incidents/{id}/acknowledge` (optional note), `/investigate`, `/resolve`, `/close`, `/reopen`
- `GET  /incidents/{id}/context`
- **No `POST /incidents/create-from-alarm` exists** — incidents are born only through the correlation engine. Verified via OpenAPI (15 incident paths).

## 2. Files

### New files (8)

| File | Purpose |
|---|---|
| `backend/alembic/versions/20260923_08_phase6_9_b_incident_lifecycle.py` | Migration |
| `backend/app/api/incidents.py` | Lifecycle + context router |
| `backend/app/incidents/incident_service.py` | Lifecycle / correlation / context services |
| `backend/app/repositories/incident.py` | `IncidentRepository` (open-status predicate, activity clock, filtered list) |
| `backend/tests/incidents/test_incident_states.py` | 11×11 transition matrix vs independent spec |
| `backend/tests/incidents/test_incident_lifecycle.py` | DB-backed command tests |
| `backend/tests/incidents/test_incident_correlation.py` | DB-backed correlation / idempotency / isolation / context tests |
| `docs/INCIDENT_LIFECYCLE.md` | Lifecycle + correlation documentation |

### Modified files (7)

| File | Change |
|---|---|
| `backend/app/incidents/states.py` | `IncidentStatus` + `INCIDENT_TRANSITIONS` + helpers |
| `backend/app/models/entities.py` | `Incident` + 6 columns + `ix_incidents_device_status` |
| `backend/app/incidents/contracts.py` | Note/lifecycle/context read contracts (+15 exports) |
| `backend/app/api/workflows.py` | Filters, additive detail context, dropped `INCIDENT_DATA_INCOMPLETE` 409 |
| `backend/app/workflow/contracts.py` | `IncidentDetailContextRead`, nullable `diagnosis_id` in summary |
| `backend/app/main.py` | Router registration |
| `backend/tests/incidents/conftest.py` | `Diagnosis` table + device fixture helper |

## 3. Database migration `20260923_08`

- `down_revision = 20260923_07`. **Additive-only**: 6 nullable columns on `incidents` (`severity`, `acknowledged_at`, `acknowledged_by`, `resolved_at`, `closed_at`, `last_alarm_at`) + `ix_incidents_device_status (device_id, status)`.
- No `incidents.status` CHECK constraint — single authority is `states.py` (rationale in migration docstring).
- **Fresh in-session verification (one-shot PostgreSQL 16.15, port 5433, seeded as-of-06 DB):**
  - `downgrade 20260923_08 → 20260923_07`: 6 columns + index removed, seeded incident row preserved (1 row) — **PASS**
  - `upgrade 20260923_07 → 20260923_08`: column list exactly matches the 14-column expectation, index present, legacy-shaped row intact with NULL new columns — **PASS**

### `alembic check` — explicit limitation

- Full-chain `alembic upgrade head` + `alembic check` from an empty database is **not executable in this environment**: migration `20260920_03_phase4_knowledge` issues `CREATE EXTENSION IF NOT EXISTS vector`, and the one-shot Zonky PostgreSQL build ships without pgvector (`vector.control` missing). The pgvector-capable image runs under Docker, and **`DOCKER_DAEMON_UNAVAILABLE`** (Docker Desktop starts then exits; reproduced with sandbox disabled).
- Compensating evidence: the targeted `20260923_08` downgrade/upgrade verification above (run twice — once during development, once fresh in this session), plus exact schema equivalence on the focused tables (0 diff).

## 4. Correlation logic summary

- **Merge rule:** an alarm on device `D` attaches to `D`'s open incident when the alarm's activity time falls within `[anchor, anchor + 600s]` (inclusive both ends — boundary tested), where `anchor = coalesce(incident.last_alarm_at, incident.created_at)`. Absorption updates `last_alarm_at` and escalates `severity`/`priority` monotonically.
- **Isolation:** devices A and B never merge (correlation key = device); cross-window alarms open separate incidents; resolved incidents do not absorb (open-status predicate only).
- **Idempotency:** `incident_alarms` unique pair `uq_incident_alarms_pair` + `on_conflict_do_nothing` — attaching the same alarm twice links once, returns the same incident.
- **Dedup:** duplicate open-alarm per (device, rule) is enforced upstream by `uq_alarms_open_device_rule` (Phase 6.9-A); the correlation layer additionally reuses existing open incidents instead of creating duplicates.

## 5. Tests

### `backend/tests/incidents` — **183 passed** (DB-backed, PostgreSQL 16.15 @ 5433)

- `test_incident_states.py` — full 11×11 matrix vs an independently written spec expectation, terminality (`CLOSED` exactly one exit; only `CANCELLED` exitless), named forbidden moves.
- `test_incident_lifecycle.py` — every lifecycle command; actor/timestamp recording; illegal moves → 409 with legal targets in payload; unknown status; unknown incident → 404; exactly one audit row per state change.
- `test_incident_correlation.py` (12 tests) — 3 alarms on device A within 10 min → 1 incident + 3 links; window boundary inclusivity; cross-window and cross-device isolation; idempotent attach; severity escalation; resolved-incident non-absorption; audit rows; context bundle with and without diagnosis.

**Failure→fix trace (from first run's 14 failures, all resolved):**
1. Lifecycle tests seeded incidents without a device row → `ForeignKeyViolation` → conftest `create_device` fixture helper.
2. `conftest` missing `Diagnosis` table → `UndefinedTable` → added to imports + `_tables()`.
3. Severity-escalation test reused one rule → `uq_alarms_open_device_rule` violation → distinct rules per alarm instance.
4. Terminality test contradicted the reopen exit → replaced with `test_closed_has_exactly_the_reopen_exit` + `test_only_cancelled_has_no_exit` (docs + docstring updated).
5. **Late defect found in final rerun (2 failures):** `IncidentContextService.device_with_asset` looked up `Device` by UUID PK (`session.get(Device, incident.device_id)`) although `incidents.device_id` is a FK to the business key `devices.device_id` → asyncpg `invalid UUID 'MOTOR-001'`. Fixed to `select(Device).where(Device.device_id == incident.device_id)`; `test_incident_correlation.py` re-run: **12/12 PASS**.

### Regression

| Suite | Command | Result |
|---|---|---|
| Backend core | `pytest tests --ignore=tests/incidents --ignore=tests/assetconfig` | **195 passed, 1 skipped** |
| Backend incidents | `pytest tests/incidents` | **183 passed** |
| Frontend | `npm test` | **29 passed (8 files)** |
| Simulator | `pytest tests` | **24 passed** |
| ML | `pytest tests` | **16 passed** |
| ruff check | `ruff check backend/` | **All checks passed** (162 files; 1 auto-fixed import sort) |
| ruff format | `ruff format backend/` | **Clean** |
| mypy | `mypy app` | **Success, 103 source files** |

## 6. Environment note

- Docker daemon unavailable → **`DOCKER_DAEMON_UNAVAILABLE`**. `docker build` and the pgvector-dependent full migration chain were not executed. All DB-backed evidence above was produced on a one-shot Zonky PostgreSQL 16.15 (port 5433, trust auth, disposable databases created/dropped per run by test conftest).

## 7. Git

- Branch: `main`, based on `112d879` (Phase 6.9-A). Local `main == origin/main` verified before work.
- Feature commit (this phase): see `git log` — "feat: implement incident lifecycle, correlation engine, and context API (Phase 6.9-B)".
- **No tag, no release, no 6.9-C work.**

## Final status: PHASE_6_9_B_COMPLETE
