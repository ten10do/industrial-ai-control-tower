# Incident Lifecycle

Phase 6.9-B gives the incident the same treatment Phase 6.9-A gave the alarm: a
single-source state machine, operator commands that move through it, a
deterministic correlation engine that merges alarm instances into incidents, and
a read-only context bundle for the phases that follow.

## Scope Boundary

This phase does not modify the workflow engine, the LangGraph graph, the safety
policy, or the work-order lifecycle. It exposes no automatic creation entry
point: there is no `POST /incidents/create-from-alarm`, and the correlation
engine is only reachable as a service. Wiring it into the telemetry path and
preparing agent context are later phases. Nothing here triggers an agent.

## Incident Definition

An incident is one correlated operational event on one device. The columns that
carry the semantics:

| Column | Meaning |
| --- | --- |
| `status` | The lifecycle state (see the state machine). |
| `severity` | Technical impact, using the same ordered vocabulary as alarms. Nullable for incidents created before this phase. |
| `priority` | Scheduling urgency, mapped deterministically from severity for engine-created incidents. |
| `acknowledged_at` / `acknowledged_by` | Set once, on the acknowledge transition. |
| `resolved_at` / `closed_at` | Set on the resolve and close transitions; cleared on reopen. |
| `last_alarm_at` | Most recent linked-alarm activity. This is the correlation anchor. |

The diagnosis association deliberately stays on the existing
`diagnoses.incident_id` foreign key. An incident can accumulate several
diagnoses across its life (a reopened investigation produces another), the
one-to-many edge is already modelled from the diagnosis side, and the spec
forbids a second link table. Adding `incidents.diagnosis_id` would duplicate the
edge into two sources of truth, so the newest diagnosis wins when a context
needs one.

## State Machine

```
OPEN ──> ACKNOWLEDGED ──> INVESTIGATING ──> MITIGATED ──> RESOLVED ──> CLOSED ──> REOPENED
   │                                                        ^                |         |
   │                                                        │                │         v
   ├──> CANCELLED                        WORK_ORDER_CREATED ─┘                └─> INVESTIGATING
   │                                           ^
   └──> UNDER_ANALYSIS ──> ACTION_PENDING ─────┘
```

The one authority is `INCIDENT_TRANSITIONS` in `app/incidents/states.py`. Every
service command goes through it; there is no second place where a legal move is
decided.

| From | To | Owner |
| --- | --- | --- |
| `OPEN` | `ACKNOWLEDGED`, `CANCELLED`, `UNDER_ANALYSIS` | Operator / workflow |
| `ACKNOWLEDGED` | `INVESTIGATING`, `CANCELLED`, `UNDER_ANALYSIS` | Operator / workflow |
| `INVESTIGATING` | `MITIGATED`, `UNDER_ANALYSIS` | Operator / workflow |
| `UNDER_ANALYSIS` | `ACTION_PENDING`, `MITIGATED` | Workflow |
| `ACTION_PENDING` | `WORK_ORDER_CREATED` | Workflow |
| `WORK_ORDER_CREATED` | `MITIGATED` | Workflow |
| `MITIGATED` | `RESOLVED` | Operator |
| `RESOLVED` | `CLOSED` | Operator |
| `CLOSED` | `REOPENED` | Operator |
| `REOPENED` | `INVESTIGATING` | Operator |
| `CANCELLED` | nothing | Terminal |

`CLOSED` ends the operator chain and has exactly one exit, an explicit reopen;
`CANCELLED` is dead by decision and nothing leaves it. The forbidden moves named in the
phase (`CLOSED → INVESTIGATING`, `CANCELLED → OPEN`) are refused with
`INCIDENT_STATE_INVALID` (409), whose payload names the current status and the
legal targets.

### Workflow-owned statuses

`workflow/service.py` already writes `UNDER_ANALYSIS`, `ACTION_PENDING`, and
`WORK_ORDER_CREATED` as raw strings, and this phase does not modify the workflow
engine. Those statuses are therefore first-class members of the transition
table: the graph stays complete, and the matrix test locks the contract the
workflow engine relies on. `incidents.status` intentionally carries no database
CHECK constraint for the same reason; a CHECK would duplicate the vocabulary
inside the migration layer without adding authority.

## Incident Service

| Command | Move | Notes |
| --- | --- | --- |
| `acknowledge_incident` | `OPEN → ACKNOWLEDGED` | Records `acknowledged_at`, `acknowledged_by`, and an optional note in the audit row. |
| `start_investigation` | `ACKNOWLEDGED → INVESTIGATING` | Also the exit of `REOPENED`. |
| `resolve_incident` | `MITIGATED → RESOLVED` | Records `resolved_at`. |
| `close_incident` | `RESOLVED → CLOSED` | Records `closed_at`. |
| `reopen_incident` | `CLOSED → REOPENED` | Clears `closed_at` and `resolved_at`; investigation restarts from there. |

Reaching `MITIGATED` is not an operator surface in this phase: the workflow-owned
chain arrives there from `WORK_ORDER_CREATED` (or directly from
`UNDER_ANALYSIS`), and the transition table records it. No mitigate endpoint is
exposed yet.

## Correlation Strategy

Strategy v1 is device plus time window, fully deterministic:

* Key: `device_id`.
* Window: 10 minutes (600 seconds), anchored on incident evidence, not on wall
  clock. The anchor is the incident's `last_alarm_at` (falling back to its
  creation time).
* Rule: if the device has a live incident (status in `OPEN_INCIDENT_STATUSES`,
  which is everything except `RESOLVED`, `CLOSED`, and `CANCELLED`) and the
  alarm's most recent activity falls inside the window, the alarm attaches.
  Otherwise a new incident opens and absorbs the alarm.

The engine-created incident takes its title, description, severity, and priority
from the opening alarm: severity maps to priority deterministically
(`CRITICAL → URGENT`, `MAJOR → HIGH`, `WARNING → MEDIUM`, `MINOR`/`INFO → LOW`).
Attaching a more severe alarm raises the incident's severity and priority; the
anchor always advances to the newest evidence, so a sustained condition keeps
one incident alive. Three alarms on one device inside ten minutes produce one
incident with three links, and devices never merge.

## Alarm Relationship

`incident_alarms` (created in 20260923_07) is the link table, and attaching is
idempotent: `attach_alarm_to_incident` relies on the unique pair constraint, so
repeating the same pair leaves exactly one row, writes no second audit record,
and cannot race into a duplicate. An alarm cannot attach to an incident on
another device; that is refused with `ALARM_INCIDENT_DEVICE_MISMATCH` (409).

Every state change writes exactly one incident-scoped `audit_events` row
(`resource` = incident id): `INCIDENT_CREATED`, `INCIDENT_ALARM_ATTACHED`,
`INCIDENT_ACKNOWLEDGED`, `INCIDENT_INVESTIGATION_STARTED`, `INCIDENT_RESOLVED`,
`INCIDENT_CLOSED`, `INCIDENT_REOPENED`. The idempotent re-attach that changes
nothing writes nothing, so the audit timeline is a faithful history.

## Context Bundle

`get_incident_context(id)` (and the additive context fields on the detail
endpoint) assemble, from persisted state only:

```
Incident
├── alarms            linked alarm instances, newest activity first
├── device            the device record
├── asset             the asset node the device hangs from, when assigned
├── diagnosis         the newest diagnosis via diagnoses.incident_id, when present
└── audit timeline    every incident-scoped audit record, oldest first
```

The bundle is read-only and does not trigger an agent, a workflow, or any write.
It is the input a later agent-facing phase will consume.

## API Surface

The lifecycle commands are registered under both `/api/v1` and `/api`; the write
path records the `X-Actor` header (default `system`).

| Method | Path | Behaviour |
| --- | --- | --- |
| `POST` | `/incidents/{id}/acknowledge` | `OPEN → ACKNOWLEDGED`. Optional note. |
| `POST` | `/incidents/{id}/investigate` | `ACKNOWLEDGED`/`REOPENED → INVESTIGATING`. |
| `POST` | `/incidents/{id}/resolve` | `MITIGATED → RESOLVED`. |
| `POST` | `/incidents/{id}/close` | `RESOLVED → CLOSED`. |
| `POST` | `/incidents/{id}/reopen` | `CLOSED → REOPENED`. |
| `GET` | `/incidents/{id}/context` | Read-only context bundle. |

The existing `GET /incidents` gained `severity` and `device_id` filters, and
`GET /incidents/{id}` gained additive context fields (`alarms`, `device`,
`asset`, `audit`); the pre-existing response fields are unchanged, so current
consumers keep working. `POST /incidents` (the operator flow from a diagnosis)
and `POST /incidents/{id}/workflows` are untouched, and no automatic creation
route exists.

## Testing

The suite lives in `backend/tests/incidents/`:

* `test_incident_states.py` covers the full 11×11 transition matrix against an
  independent, spec-derived expectation, terminality, and the named forbidden
  moves.
* `test_incident_lifecycle.py` is database-backed: every command, the recorded
  actor and timestamps, refused illegal moves with their legal targets, unknown
  statuses, and one-audit-row-per-state-change.
* `test_incident_correlation.py` is database-backed: three alarms in the window
  to one incident with three links, window boundary inclusivity, cross-window
  and cross-device isolation, attach idempotency, severity escalation, resolved
  incidents not absorbing new evidence, audit rows, and the context bundle with
  and without a diagnosis.

Database-backed tests are opt-in through `ALARM_TEST_DATABASE_URL` and skip when
the variable is absent.
