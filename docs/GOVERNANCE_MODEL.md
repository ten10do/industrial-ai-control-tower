# Governance Model — Phase 6.13-C

## Purpose

This document describes the enterprise governance and compliance layer added in
Phase 6.13-C on top of the Phase 6.12 authentication and RBAC foundation, the
Phase 6.13-A authenticated-actor migration, and the Phase 6.13-B enterprise
organization model.

Five capabilities, all additive:

1. **Audit governance** — filtered, paged queries over the one `audit_events`
   table.
2. **Change management** — a change-record ledger with a lifecycle state
   machine.
3. **Governance Policy Engine** — conditional DENY rules evaluated above RBAC
   on every governed route.
4. **Compliance dashboard** — one read-only aggregate over the existing
   tables.
5. **Security event audit** — the security-boundary slice of the audit trail,
   with an aggregation.

## What this phase is not

- **Not a second audit system.** The governance surface reads the existing
  `audit_events` table through new read methods on `AuditRepository`. The
  incident timeline and the configuration audit keep their own queries.
- **Not a second approval or workflow system.** A change record *records* a
  change; it never performs or approves one. The Workflow / Approval state
  machines are untouched.
- **Not a second Device/Asset system.** The governance layer adds no device
  or asset tables at all.
- **Not a bypass of the Policy Layer.** Every permission decision still flows
  through the unified decision point `require_permission`: RBAC first, the
  governance Policy Engine second, the Scope Policy at the route body for
  device-scoped surfaces.

## Data model (two tables, both additive)

`backend/app/security/governance_models.py`

### `governance_policies`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | String(200), unique | |
| `description` | String(500) | |
| `effect` | String(10), `DENY` only | A policy can only refuse; a grant would be a second authorization system |
| `permission` | String(100) | A name from the RBAC vocabulary; validated at write time |
| `conditions` | JSONB | See the condition table below; validated at write time |
| `enabled` | Boolean | A disabled policy is skipped entirely |

### `change_records`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `title` / `description` | String | |
| `change_type` | `CONFIGURATION` / `HARDWARE` / `PROCEDURE` | Check-constrained |
| `risk_level` | `LOW` / `MEDIUM` / `HIGH` | Check-constrained; the dashboard aggregates by it |
| `status` | `DRAFT` / `SCHEDULED` / `IN_PROGRESS` / `COMPLETED` / `CANCELLED` | Check-constrained |
| `resource_type` / `resource_id` | nullable strings | What the change concerns; informational |
| `requested_by_user_id` / `requested_by_name` | nullable | Immutable references, no foreign key, in the audit-trail tradition: deleting an identity cannot erase who asked for a change |
| `scheduled_start` / `scheduled_end` | nullable timestamptz | The execution window; a check constraint refuses an inverted window |

Indexes: `ix_governance_policies_enabled`, `ix_change_records_status`,
`ix_change_records_window`.

## Policy Engine

`backend/app/security/policy_engine.py`. One module decides; no route consults
`governance_policies` itself. The single enforcement point is
`require_permission` (`app/security/dependencies.py`): after the RBAC check
passes, the engine evaluates every enabled `DENY` policy naming that
permission, in name order, and the first match refuses.

### Conditions

All keys present must match (AND).

| Condition | Shape | Matches when |
|---|---|---|
| always | `{"always": true}` | Every request. The change freeze: an unconditional DENY binds everyone, including ADMIN |
| roles | `{"roles": ["OPERATOR", …]}` | The caller holds any listed role |
| time_window | `{"time_window": {"days": [1..7], "start": "HH:MM", "end": "HH:MM"}}` | Request arrives inside the UTC window; ISO weekdays (Monday=1); end ≤ start wraps midnight |

Write-time validation (422 `POLICY_CONDITION_INVALID`):

- unknown condition keys, so a typo cannot ship a rule that enforces nothing;
- empty or non-string role lists; non-ISO weekdays; malformed clock times;
- `always` combined with any other key.

A rule edited out-of-band into an unsupported shape is **inert** at evaluation
time (it never matches), never a 500. Inert does not mean silent (Phase
6.13-D): the evaluation emits a structured warning naming the policy,
increments `governance_invalid_policy_total`, and the compliance dashboard
reports the invalid count, so a rule that enforces nothing is visible.

### Fail-closed semantics (Phase 6.13-D)

The database session is a required dependency of evaluation; the former
`session=None → allowed` compatibility branch is removed. The full matrix:

| Situation | Behaviour |
|---|---|
| No matching enabled DENY policy | The RBAC + scope answer stands |
| Policy matches | `403 POLICY_DENIED`, audited before the raise |
| Stored condition the engine cannot interpret | Inert for the request; structured warning + counter + dashboard invalid count |
| Governance database unavailable | `503 GOVERNANCE_UNAVAILABLE` — never an `ALLOW` |
| Unexpected evaluator exception | `503 GOVERNANCE_UNAVAILABLE`, counted in `governance_evaluation_error_total`, structured log |

### Refusal semantics

`403 POLICY_DENIED`, audited as `action=POLICY_DENIED`, `status=DENIED`, with
the policy name, permission, method, path, and acting identity, written before
the exception is raised. The evaluate endpoint
(`POST /governance/policies/evaluate`) answers the same question without side
effects. A refusal never mutates business state: the denial is decided before
the route body runs, and the tests assert the refused object (alarm, change
record) is unchanged.

## Change management

The lifecycle is a code-owned state machine
(`CHANGE_TRANSITIONS` in `governance_models.py`), enforced at the API boundary
with 409 `INVALID_CHANGE_TRANSITION`:

```
DRAFT ──▶ SCHEDULED ──▶ IN_PROGRESS ──▶ COMPLETED
  │            │              │
  └──▶ CANCELLED ◀────────────┘
```

- Scheduling (`DRAFT → SCHEDULED`) requires an execution window, supplied on
  the record or in the transition request; `scheduled_end` must be after
  `scheduled_start` (API 422 and a database check constraint).
- A window may only be supplied when scheduling (409 otherwise).
- Only a `DRAFT` record is editable (409 `CHANGE_NOT_EDITABLE` otherwise): once
  scheduled, the record is the plan people may have acted on.
- A `COMPLETED` or `CANCELLED` record is history; it cannot resurrect.
- Every mutation writes `CHANGE_RECORD_CREATED` / `CHANGE_RECORD_UPDATED` /
  `CHANGE_RECORD_TRANSITIONED` rows attributed to the authenticated caller.

## API surface

`backend/app/api/governance.py`, mounted under `/api/v1` and `/api`.

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/governance/audit` | `audit.read` | Filters: actor, action, resource, resource_id, status, trace_id, since, until; page ≤ 200 rows, newest first, with total |
| GET | `/governance/security-events` | `audit.read` | The security-boundary actions only, plus a counts-by-action/status aggregation |
| GET | `/governance/compliance/dashboard` | `governance.read` | `window_days` 1–90; audit totals by status, security-event summary, policy counts, change counts by status, high-risk open count, identity counts, last audit timestamp |
| GET | `/governance/policies`, `/governance/policies/{id}` | `governance.read` | |
| POST | `/governance/policies` | `governance.manage` | 409 `POLICY_EXISTS` on duplicate name |
| PATCH | `/governance/policies/{id}` | `governance.manage` | |
| DELETE | `/governance/policies/{id}` | `governance.manage` | |
| POST | `/governance/policies/evaluate` | `governance.read` | What-if evaluation, no side effects |
| GET | `/governance/changes`, `/governance/changes/{id}` | `change.read` | Filters: status, risk_level, type |
| POST | `/governance/changes` | `change.manage` | Creates in `DRAFT` |
| PATCH | `/governance/changes/{id}` | `change.manage` | `DRAFT` only |
| POST | `/governance/changes/{id}/transition` | `change.manage` | The state machine |

### Permission grants (migration `20260924_12`)

| Permission | ADMIN | OPERATOR | VIEWER |
|---|---|---|---|
| `audit.read` | via `*` | yes | no (the trail carries source addresses) |
| `governance.read` | via `*` | yes | yes |
| `governance.manage` | explicit | no | no |
| `change.read` | via `*` | yes | yes |
| `change.manage` | via `*` | yes | no |

## Compliance dashboard semantics

Nothing is cached or copied. Every number is computed at request time from
`audit_events`, `governance_policies`, `change_records`, and `users`, so the
dashboard cannot disagree with the evidence it summarizes. The window is
bounded at 90 days to keep the query a dashboard aggregate rather than a
full-table export in disguise. Phase 6.13-D adds `policies.invalid`: the
count of stored rules whose conditions the engine cannot interpret (they are
inert at evaluation time), so "how many rules enforce nothing" is one read.

## Migration

`backend/alembic/versions/20260924_12_phase6_13_c_governance.py`
(revision `20260924_12`, down_revision `20260924_11`):

- Creates the two tables with their check constraints and indexes.
- Seeds the five permission rows and their role grants.
- Downgrade: drops the tables and deletes exactly the seeded permission rows —
  a pure subtraction.

Seeding is duplicated from `app.security.rbac.ROLE_PERMISSIONS` on purpose, as
in every security migration before this one; the parity test compares the
combined seed of all four security migrations against the code table and
asserts each slice is disjoint.

## Non-goals (explicit)

- No policy grants, no per-identity policy exceptions, no policy priorities
  beyond deterministic name order.
- No change-record approval gates: the Approval state machine already exists
  and is untouched.
- No audit retention/export: the dashboard window is a read bound, not a
  retention policy.
- No frontend dashboard page in this phase; the API is the contract.
- No changes to LangGraph/Agent/RAG/ML/Workflow/Approval/WorkOrder state
  machines.

## Verification

- `backend/tests/security/test_governance.py` — DB-backed (opt-in, real
  PostgreSQL): policy CRUD validation and gating, enforcement above RBAC with
  audited refusals, disabled-policy behaviour, inert malformed rules,
  evaluate endpoint, the change state machine including window rules and
  role gating, audit query filters, the security-event slice, dashboard
  aggregates, schema indexes, and the inverted-window database constraint.
  Pure-function condition-matching tests run without a database.
- `backend/tests/security/test_route_coverage.py` — the governance prefix
  added to the governed surface and the permission matrix.
- `backend/tests/security/test_rbac_vocabulary.py` — the 6.13-C migration
  joins the parity, additive-disjoint, and revision-chain assertions.
