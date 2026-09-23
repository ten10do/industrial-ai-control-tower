# Phase 6.9-A Final Report: Alarm Lifecycle Foundation & Incident Correlation Foundation

## 1. Result Summary

| Item | Result |
|---|---|
| Implementation | Alarm lifecycle (ACTIVE → ACKNOWLEDGED → CLEARED), alarm rule registry, incident correlation foundation, 14 API endpoints |
| Database migration | `20260923_07` verified upgrade → downgrade → upgrade on a real PostgreSQL 16 with seeded duplicate data; backfill, partial unique index, and seeded rules all verified |
| New tests | 124 (states 15, rules 55, lifecycle 30, rule service 24) |
| Backend total | 435 passed, 1 skipped, 1 environment-blocked error (pgvector extension unavailable on the disposable verification server) |
| Static analysis | Ruff clean, ruff format clean (155 files), mypy clean (137 source files) |
| Frontend regression | 29 passed (vitest) |
| Simulator regression | 24 passed |
| ML regression | 16 passed |
| Docker build | BLOCKED: `DOCKER_DAEMON_UNAVAILABLE` (see §12) |
| Git | 1 feature commit on `main`, no tag, no release |
| Status | COMPLETE, awaiting acceptance. Phase 6.9-B not started |

## 2. Baseline

Repository `D:\industrial-ai-control-tower`, branch `main`, release `v1.6.0`, HEAD
`2c2f216a34885efc4a12736dc18fc6d4aab80078`. The phase was implemented on top of the
approved `PHASE_6_9_ARCHITECTURE_DESIGN_REPORT.md` (committed with this phase).

## 3. Implementation

### 3.1 Alarm semantic promotion

The `alarms` table was promoted from a per-sample rule trigger log to an active
condition instance registry. One sustained condition on one device is now one row
whose `occurrence_count` and `last_triggered_at` record the volume that the row
count used to. `started_at` and `telemetry_id` keep pointing at the first breach
and are never rewritten. A new instance anchors at the telemetry sample's event
time, not at ingestion wall clock time.

The deduplication invariant is enforced twice: in application code through
`AlarmLifecycleService.create_or_update_alarm` (open instance exists → update in
place), and in the database through the partial unique index
`uq_alarms_open_device_rule` over `(device_id, rule_id) WHERE status <> 'CLEARED'`.
The service writes inside a savepoint and resolves the insert race by retrying the
update branch when a second worker loses the index race.

### 3.2 Alarm rule registry

`alarm_rules` promotes the two thresholds that were string literals in
`TelemetryService._apply_alarm_rules` into declarative data. The migration seeds
`HIGH_TEMPERATURE` (temperature > 90, CRITICAL/URGENT) and `HIGH_VIBRATION`
(vibration > 7, WARNING/HIGH) with their exact original values, so behaviour after
upgrade is identical to behaviour before it. `enabled` retires a rule without
deleting it; `device_type` scopes a rule to a type, and a null scope applies to
every device. `SIGNAL_SPECS` in `app/incidents/rules.py` is the single authority
mapping canonical signal names (no unit suffix) to telemetry contract fields, and
validation rejects thresholds outside each signal's physical range.

Rule evaluation stays contained: it runs in a savepoint inside telemetry
ingestion, so a broken rule produces a missing alarm plus an `ALARM_EVALUATION_FAILED`
audit row, never a rejected telemetry sample.

### 3.3 Incident correlation foundation

`app/incidents/correlation.py` provides `find_related_alarm` and
`find_related_alarms` only. An open instance qualifies regardless of age; a
cleared instance qualifies when its last activity falls inside the window
(default 300 s, maximum 86 400 s). A naive reference datetime is refused with
`CORRELATION_WINDOW_INVALID` (422). Nothing in this phase creates an incident,
mutates one, or links an alarm to one. `incident_alarms` exists as the idempotent
many-to-many link table and the detail endpoint resolves `incident_ids` read-only;
no row is written to it in this phase.

### 3.4 Audit policy

`audit_events` records state changes only: `ALARM_RULE_CREATED`,
`ALARM_RULE_UPDATED`, `ALARM_CREATED`, `ALARM_ACKNOWLEDGED`, `ALARM_CLEARED`, and
`ALARM_EVALUATION_FAILED`. A repeated breach that only increments an open instance
writes nothing; the volume lives in `occurrence_count`. `observability_*` tables
are untouched.

## 4. Files

### 4.1 New files

| File | Purpose |
|---|---|
| `backend/app/incidents/states.py` | Lifecycle vocabulary, guarded transition table, severity/priority ordering |
| `backend/app/incidents/errors.py` | `AlarmLifecycleError` family (404/409/422 codes) |
| `backend/app/incidents/models.py` | `AlarmRule` and `IncidentAlarm` tables, rule vocabulary constants |
| `backend/app/incidents/rules.py` | Signal specs, comparison engine, message rendering, definition validator |
| `backend/app/incidents/contracts.py` | Alarm/alarm-rule request and response contracts |
| `backend/app/incidents/correlation.py` | `find_related_alarm` / `find_related_alarms` |
| `backend/app/incidents/service.py` | `AlarmRuleService` and `AlarmLifecycleService` |
| `backend/app/incidents/__init__.py` | Dependency-free re-exports |
| `backend/app/api/alarm_rules.py` | Rule registry router (GET/POST/PATCH) |
| `backend/app/repositories/alarm_rule.py` | Rule persistence |
| `backend/app/repositories/incident_alarm.py` | Idempotent incident-alarm linkage |
| `backend/alembic/versions/20260923_07_phase6_9_a_alarm_lifecycle.py` | Migration `20260923_07` |
| `backend/tests/incidents/` (conftest + 4 modules) | 124 tests |
| `docs/ALARM_LIFECYCLE.md` | Alarm definition, lifecycle, deduplication, incident relationship |
| `PHASE_6_9_ARCHITECTURE_DESIGN_REPORT.md` | Approved design input for this phase |

### 4.2 Modified files

| File | Change |
|---|---|
| `backend/app/models/entities.py` | `Alarm` gained `acknowledged_at/by`, `clear_reason`, `occurrence_count`, `last_triggered_at`, status CHECK, partial unique index, open-status index; `uq_alarm_telemetry_rule` retained |
| `backend/app/models/__init__.py` | Re-export `AlarmRule`, `IncidentAlarm` |
| `backend/app/repositories/alarm.py` | `find_open`, `list_instances`, `related`, windowed correlation queries |
| `backend/app/api/alarms.py` | Lifecycle endpoints (acknowledge/clear/detail/related), dual-prefix alignment |
| `backend/app/services/telemetry.py` | Rule evaluation delegated to `AlarmLifecycleService.record_breaches` inside a savepoint, with containment audit |
| `backend/app/main.py` | Router registration (dual prefix), `AlarmLifecycleError` handler |
| `backend/app/schemas/alarm.py` | Deleted (superseded by `app/incidents/contracts.py`) |

No file outside `backend/` was modified except documentation. Frontend, Agent
Workflow, LangGraph, Safety Policy, WorkOrder, ML, RAG, and Protocol Adapter code
are untouched, verified by `git status`.

## 5. Database Migration: `20260923_07`

Verified on a disposable PostgreSQL 16.15 (Zonky binaries, port 5433, trust auth,
drop-after). Because the full migration chain from empty requires the pgvector
extension (migration `20260920_03`), the verification targeted this phase's
revision: the database was built to the exact as-of-`20260922_06` schema from
HEAD models, seeded, stamped `20260922_06`, and the revision was then exercised
through the real alembic runner.

Seeded scenario: device DEV-A holds three ACTIVE rows for one rule (the
pre-migration duplicate shape), DEV-B holds one ACTIVE row, plus one
pre-existing CLEARED row.

### 5.1 Upgrade (12/12 PASS)

| Check | Result |
|---|---|
| `alarm_rules` seeded with exact original thresholds (90.0 / 7.0, GT, severities, priorities, enabled) | PASS |
| Backfill: earliest duplicate row stays ACTIVE, absorbs group (`occurrence_count` = 3, `last_triggered_at` = group max) | PASS |
| Backfill: later duplicates relabelled CLEARED with `clear_reason = 'SUPERSEDED_ON_MIGRATION_20260923_07'`, `occurrence_count` = 1 | PASS |
| Single open row and pre-existing CLEARED row untouched | PASS |
| `uq_alarms_open_device_rule` present with the exact partial predicate | PASS |
| `ix_alarms_open_status_device`, CHECK constraints present; `uq_alarm_telemetry_rule` retained | PASS |
| `incident_alarms` with unique pair + both FKs (CASCADE) | PASS |
| Second open insert for the same device+rule refused (`UniqueViolation`) | PASS |

### 5.2 Downgrade (9/9 PASS)

All five columns, both CHECK constraints, both new indexes, and both new tables
removed; base columns and `uq_alarm_telemetry_rule` restored; row count preserved
(5). The consolidated CLEARED labels survive, which is the documented
non-recoverability of the backfill.

### 5.3 Re-upgrade (PASS, with two documented roundtrip limitations)

The second upgrade succeeds and rebuilds every object. Two facts are inherent to
a lossy downgrade and are now documented in the migration docstring and in
`docs/ALARM_LIFECYCLE.md`:

1. The absorbed `occurrence_count` of the consolidated instance restarts at 1,
   because the downgrade dropped the column that carried it.
2. `clear_reason` is recreated as NULL, so the `SUPERSEDED` marker of relabelled
   rows is not restorable after a downgrade/re-upgrade roundtrip.

### 5.4 Targeted schema equivalence (substitute for full `alembic check`)

`alembic check` requires a server holding the complete schema including pgvector
tables. As an honest substitute, alembic autogenerate comparison was run against
the upgraded database filtered to the seven tables this phase touches (alarms,
alarm_rules, incident_alarms, devices, telemetry, incidents, audit_events):
`SCHEMA_DIFF_ITEMS=0` PASS.

## 6. Alarm Lifecycle State Machine

```
ACTIVE ──> ACKNOWLEDGED ──> CLEARED
   │              │
   └──────────────┴──────────> CLEARED
```

| From | To | Result |
|---|---|---|
| ACTIVE | ACKNOWLEDGED | Allowed, records `acknowledged_at`/`acknowledged_by` |
| ACTIVE | CLEARED | Allowed, records `cleared_at`/mandatory `clear_reason` |
| ACKNOWLEDGED | CLEARED | Allowed |
| ACKNOWLEDGED | ACTIVE | Allowed (acknowledgement withdrawal) |
| CLEARED | anything | Refused, `ALARM_STATE_INVALID` 409; recurrence opens a new instance |

The transition table lives in one place (`app/incidents/states.py`) and is tested
against an independent 3×3 expectation matrix.

## 7. Tests

New suite `backend/tests/incidents/`, 124 tests:

| Module | Count | Nature |
|---|---|---|
| `test_states.py` | 15 | Pure: full transition matrix, CLEARED terminality, severity ordering |
| `test_rules.py` | 55 | Pure: signal mapping probed at every telemetry contract bound, operator boundaries, scope/skip behaviour, validator codes |
| `test_lifecycle.py` | 30 | DB-backed: 100 breaches → 1 instance, lifecycle moves, refused illegal moves, history preservation, recurrence, race resolution, DB invariant, audit policy, no-incident-creation |
| `test_rule_service.py` | 24 | DB-backed: rule CRUD semantics, audit rows, conflict/validation errors, applicability scoping |

Defects found and fixed during verification:

1. The test fixture omitted `asset_nodes`, which `devices` references by FK; the
   fixture now creates it first.
2. `record_breaches` anchored new instances at wall clock when the caller omitted
   `triggered_at`. The service now derives the instant from the payload's
   `timestamp` (falling back to wall clock only when absent or unparseable), and
   production callers that pass `data.timestamp` explicitly are unaffected.
3. One correlation test asserted semantics that contradicted the documented
   `include_open=False` behaviour; the test now exercises both the
   recent-activity inclusion and the window-exclusion cases.
4. An empty rule name is refused by the request contract (422) before the service
   validator runs; the test accepts either rejection path and still asserts
   nothing is stored.

## 8. Regression

| Suite | Result |
|---|---|
| Backend core (`pytest tests`, excluding DB opt-in suites) | 195 passed, 1 skipped |
| Backend incidents (DB-backed, new) | 124 passed |
| Backend assetconfig + observability integration (DB-backed) | 116 passed, 1 error |
| Frontend (`vitest run`) | 29 passed |
| Simulator (`pytest`) | 24 passed |
| ML (`pytest`) | 16 passed |

The single error is
`tests/test_observability_integration.py::test_real_workflow_produces_observability_data`,
which fails during fixture setup with
`extension "vector" is not available` on the disposable verification server. It is
an environment limitation (no pgvector on the embedded server), unrelated to this
phase's changes; the same suite's non-DB part is inside the 195 core passes. The
assetconfig integration chain (113 tests, publish → gateway → ingestion →
telemetry rows) passed fully, which exercises the modified `TelemetryService`
end to end.

## 9. Static Analysis

| Check | Result |
|---|---|
| `ruff check .` | All checks passed |
| `ruff format --check .` | 155 files already formatted |
| `mypy app tests` | Success, no issues in 137 source files |

## 10. API Surface

14 paths registered under both `/api/v1` and `/api`:

- `GET/POST /alarm-rules`, `GET/PATCH /alarm-rules/{rule_id}`
- `GET /alarms`, `GET /alarms/related`, `GET /alarms/{alarm_id}`
- `POST /alarms/{alarm_id}/acknowledge`, `POST /alarms/{alarm_id}/clear`

`POST /incidents` and the incident creation logic are untouched. Write paths
record the `X-Actor` header (default `system`).

## 11. Observability Compatibility

`observability_runs`, `observability_steps`, and `observability_metrics` are
untouched. Traces continue through `audit_events`.

## 12. Docker

`DOCKER_DAEMON_UNAVAILABLE`. Docker Desktop on this machine starts and then exits
without ever creating the engine pipe (`dockerDesktopLinuxEngine`); the failure
reproduced with the sandbox disabled, so the daemon cannot be reached from any
command in this session. Consequently:

- `docker build` for the backend image: NOT EXECUTED (blocked, not skipped).
- Full-chain `alembic upgrade head` from an empty database: NOT EXECUTED (the
  pgvector extension ships in the Docker image). The targeted single-revision
  verification in §5 is the substitute evidence, and `docs/ALARM_LIFECYCLE.md`
  plus the test fixture make the pgvector-free path explicit.

No verification in this report is fabricated; every number above comes from an
executed command whose log is retained under `.workbuddy/pgtool/`.

## 13. Git Commit Status

One feature commit on `main` (no tag, no release), created after every gate above
passed. See `git log -1` for the hash and `git status` for a clean tree.

## 14. Scope Discipline

Delivered exactly what Phase 6.9-A allows. No second Incident entity, no
automatic Alarm → Incident chain, no Incident Center UI, no Release, no Tag.
Phase 6.9-B has not been started. Awaiting acceptance.
