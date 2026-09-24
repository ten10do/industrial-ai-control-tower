# Alarm Lifecycle

Phase 6.9-A promotes the alarm from a per-sample rule trigger record to an active
condition lifecycle instance. One sustained condition on one device now produces
exactly one alarm row that accumulates occurrences, instead of one row per
telemetry sample that breached a threshold.

## Scope Boundary

This phase delivers the lifecycle foundation, the rule registry, and the incident
correlation lookup. It does not deliver automatic incident creation, the incident
center UI, or any Alarm to Incident automation. Those belong to Phase 6.9-B.
Nothing in the alarm write path creates, mutates, or links an incident.

## Alarm Definition

An alarm is a named condition instance: one device, one rule, one open lifecycle.
The columns that carry the semantics:

| Column | Meaning |
| --- | --- |
| `device_id` | The device the condition belongs to. |
| `rule_id` | The rule whose threshold the condition violates. |
| `status` | `ACTIVE`, `ACKNOWLEDGED`, or `CLEARED`. |
| `severity` / `priority` | Copied from the rule at breach time. Severity is technical impact; priority is scheduling urgency. They are independent axes. |
| `started_at` | First breach of the condition. Never moves. |
| `last_triggered_at` | Most recent breach. Moves forward only. |
| `occurrence_count` | Number of telemetry samples that breached while the instance was open. |
| `telemetry_id` | The telemetry sample that opened the condition. |
| `acknowledged_at` / `acknowledged_by` | Set once, on the acknowledge transition. |
| `cleared_at` / `clear_reason` | Set once, on the clear transition. The reason is mandatory. |

An unknown or absent severity is treated as below every severity floor. The
default under-promotes rather than over-promotes.

## Alarm Rules

Thresholds are data, not code. The `alarm_rules` table registers each rule with a
canonical signal name, a comparison operator, a threshold, a severity, and a
priority. `enabled` retires a rule without deleting it, so historical alarms that
name the rule stay explainable. A rule scoped with `device_type` applies only to
that type; a rule with a null `device_type` applies to every device.

The migration seeds the two thresholds that previously lived in
`TelemetryService._apply_alarm_rules` with their exact original values
(`HIGH_TEMPERATURE`, temperature > 90, CRITICAL; `HIGH_VIBRATION`, vibration > 7,
WARNING), so no behaviour changes on upgrade.

Rule authoring cannot reach a device. A rule names a signal, a comparison, and a
threshold; evaluation reads telemetry and writes alarm state.

### Signal Names

Canonical signal names carry no unit suffix. The telemetry contract columns do.

| Canonical name | Telemetry field | Unit |
| --- | --- | --- |
| `temperature` | `temperature_c` | °C |
| `vibration` | `vibration_mm_s` | mm/s |
| `pressure` | `pressure_kpa` | kPa |
| `flow_rate` | `flow_rate_m3h` | m³/h |
| `humidity` | `humidity_pct` | % |
| `current` | `current_a` | A |
| `voltage` | `voltage_v` | V |
| `rotating_speed` | `rotating_speed_rpm` | rpm |

`SIGNAL_SPECS` in `app/incidents/rules.py` is the single authority for this
mapping and for the physical range of each signal. Validation rejects a threshold
outside the physical range with the stable code `THRESHOLD_OUT_OF_RANGE`.

## Lifecycle

```
ACTIVE ──> ACKNOWLEDGED ──> CLEARED
   │              │
   └──────────────┴──────────> CLEARED
```

`CLEARED` is terminal. A recurrence opens a new instance, so history stays
attributable. The transition table in `app/incidents/states.py` is the one place a
legal move is declared, and every service-level move goes through it.

| From | To | Result |
| --- | --- | --- |
| `ACTIVE` | `ACKNOWLEDGED` | Allowed. Records `acknowledged_at` and `acknowledged_by`. |
| `ACTIVE` | `CLEARED` | Allowed. Records `cleared_at` and the mandatory reason. |
| `ACKNOWLEDGED` | `CLEARED` | Allowed. |
| `ACKNOWLEDGED` | `ACTIVE` | Allowed. An operator can withdraw an acknowledgement. |
| `CLEARED` | anything | Refused with `ALARM_STATE_INVALID` (409). |

A repeat acknowledge is refused, and clearing an already cleared instance is
refused, because both would overwrite facts an operator recorded.

## Deduplication

`AlarmLifecycleService.create_or_update_alarm` is the only write path that opens
an instance. For a given device and rule:

1. If an open instance exists (`ACTIVE` or `ACKNOWLEDGED`), the breach updates it:
   `occurrence_count` increments by one and `last_triggered_at` moves forward if
   the sample is newer. Status is never changed by a breach.
2. Otherwise a new instance opens with `occurrence_count = 1`.

An acknowledged instance absorbs later breaches. It does not flip back to
`ACTIVE`, because an operator has already seen the condition.

A new instance anchors at the telemetry sample's event time, so `started_at`
reflects when the condition began rather than when the sample was ingested. The
caller may pass the instant explicitly; when it does not, the service derives it
from the payload's `timestamp` and falls back to wall clock only when that is
absent or unparseable.

The database enforces the same invariant. The partial unique index
`uq_alarms_open_device_rule` covers `(device_id, rule_id)` where
`status <> 'CLEARED'`, so at most one open instance per device and rule can exist
even under a race. The service writes inside a savepoint and resolves the race by
retrying the update branch when the insert loses the index race.

### Migration Backfill

Historical data violated the new invariant: a sustained condition used to produce
one row per sample. Migration `20260923_07` therefore consolidates before it
builds the index. The earliest row per device and rule keeps its identity and
absorbs the group (`occurrence_count` = group size, `last_triggered_at` = group
maximum). Later rows are relabelled `CLEARED` with
`clear_reason = 'SUPERSEDED_ON_MIGRATION_20260923_07'`. No row is deleted, so the
downgrade is lossless at the schema level and `uq_alarm_telemetry_rule` can always
be recreated. Two limitations are documented in the migration. First, the
pre-migration statuses of relabelled rows cannot be restored. Second, a downgrade
removes the `clear_reason` column itself, so a subsequent re-upgrade cannot
restore the `SUPERSEDED` marker and the relabelled rows stop being
distinguishable from organically cleared rows. While the revision stays applied,
the affected rows remain identifiable by their `clear_reason`.

### Known Limitation

A live condition that normalizes does not clear itself. Clearing requires evidence
that the condition is gone, and inferring it from the absence of a breaching
sample would need a dead-man timer, which is deferred to a later phase. An open
instance stays `ACTIVE` or `ACKNOWLEDGED` until an operator clears it.

## Relationship with Incident

An incident is assembled from alarms; it is never created by an alarm. This phase
provides the lookup only:

* `find_related_alarm(session, device_id, rule_id, window_seconds, reference)`
  returns the alarm instance that already relates to a device and rule. An open
  instance wins regardless of age. Only when no instance is open does the window
  apply, and the most recently active cleared instance wins.
* `find_related_alarms(...)` returns every instance related to a device inside a
  window, which is the evidence set a future incident will be assembled from.

The default window is 300 seconds and the maximum is 86 400. The reference
instant must be timezone-aware; a naive datetime is refused with
`CORRELATION_WINDOW_INVALID` (422) because it would be interpreted in the server's
local zone and could silently shift the window by hours.

`incident_alarms` is the many-to-many link table with a unique pair constraint.
Linking is idempotent, and this phase writes no rows into it. The detail endpoint
resolves `incident_ids` read-only.

## API Surface

All routes are registered under both `/api/v1` and `/api`, matching the Phase 6.6
and 6.8 convention. Since Phase 6.13-A every route declares a permission through
`require_permission`, and the write path records the authenticated caller as the
actor. A legacy `X-Actor` header, when a client still sends one, is kept only as
audit metadata (`details["legacy_x_actor"]`) and grants no authority.

### Rules

| Method | Path | Behaviour |
| --- | --- | --- |
| `GET` | `/alarm-rules` | List rules, or only enabled ones with `enabled_only=true`. |
| `POST` | `/alarm-rules` | Register a rule (201). Validation failures return 422; a duplicate id returns 409. |
| `GET` | `/alarm-rules/{rule_id}` | One rule (404 when unknown). |
| `PATCH` | `/alarm-rules/{rule_id}` | Patch a rule. Unset fields are untouched; an explicit null `device_type` widens the rule to all types. |

### Alarms

| Method | Path | Behaviour |
| --- | --- | --- |
| `GET` | `/alarms` | Filter by `device_id`, `status`, `severity`, `rule_id`, `since`, `active_only`. |
| `GET` | `/alarms/related` | Correlation lookup for a device inside a window. |
| `GET` | `/alarms/{alarm_id}` | Detail, including `incident_ids`. |
| `POST` | `/alarms/{alarm_id}/acknowledge` | `ACTIVE -> ACKNOWLEDGED`. Optional note (max 500 chars). |
| `POST` | `/alarms/{alarm_id}/clear` | `ACTIVE`/`ACKNOWLEDGED -> CLEARED`. Reason required (3 to 500 chars). |

`POST /incidents` and the incident creation logic are untouched by this phase.

## Audit Policy

State changes write one `audit_events` row each: `ALARM_RULE_CREATED`,
`ALARM_RULE_UPDATED`, `ALARM_ACKNOWLEDGED`, `ALARM_CLEARED`, and
`ALARM_EVALUATION_FAILED`. Activity volume writes nothing: a repeated breach that
only increments an open instance is telemetry, and it is observable through
`occurrence_count` and `last_triggered_at`.

Rule evaluation is contained in a savepoint inside telemetry ingestion. A failing
rule rolls back only the alarm work, the telemetry sample still commits, and the
failure is audited. A broken rule can never reject a telemetry sample.

## Observability Compatibility

`observability_runs`, `observability_steps`, and `observability_metrics` are
untouched. Traces continue through `audit_events`.

## Testing

The suite lives in `backend/tests/incidents/`:

* `test_states.py` covers the full transition matrix as an independent
  expectation, terminality of `CLEARED`, and severity ordering.
* `test_rules.py` covers the pure rule engine: signal mapping against the
  telemetry contract bounds, operator boundaries, scope and skip behaviour,
  message rendering, and validator codes.
* `test_lifecycle.py` is database-backed: deduplication (100 breaches to 1
  instance), the full lifecycle, refused illegal moves, history preservation,
  recurrence, race resolution, the partial unique index as a hard invariant, and
  the absence of any incident creation from the alarm path.
* `test_rule_service.py` is database-backed: rule CRUD semantics, audit rows,
  conflict and validation errors, and applicability scoping.

Database-backed tests are opt-in through `ALARM_TEST_DATABASE_URL` and skip when
the variable is absent.
