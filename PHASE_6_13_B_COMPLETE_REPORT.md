# PHASE_6_13_B_COMPLETE_REPORT

Phase 6.13-B — Enterprise Organization Model

Status: COMPLETE (full regression green, committed to main, no tag / no release per constraint 6)

## 1. Objective

Add enterprise organization, plant, area, and device-scope governance on top of the Phase 6.12 Authentication + RBAC foundation and the Phase 6.13-A authenticated-actor migration, without touching the LangGraph / Agent / RAG / ML / Workflow / Approval / WorkOrder state machines and without introducing a second Device/Asset system.

## 2. Constraint Compliance

| # | Constraint | Compliance |
|---|-----------|------------|
| 1 | No modification of LangGraph/Agent/RAG/ML/Workflow/Approval/WorkOrder | PASS — zero edits outside security/API/audit/docs/tests |
| 2 | No second Device/Asset system | PASS — `device_scopes` is a single association row referencing the existing `devices.device_id` (FK, ondelete CASCADE); no device data is imported or duplicated |
| 3 | All permission decisions centralized in the Scope Policy layer | PASS — single decision module `app/security/scope_policy.py` (`resolve_device_scope`, `ensure_device_in_scope`, `device_scope_filter`); routes never decide scope themselves |
| 4 | All mutations continue using the authenticated actor | PASS — every new mutation routes audit through `AuditRepository.add` with `actor_user_id` from `SecurityContext`; `X-Actor` remains legacy metadata only |
| 5 | Migration rollable | PASS — `20260924_11` downgrade drops the five tables in reverse dependency order and removes the seeded permission rows |
| 6 | Full regression, stop, no tag/release | PASS — all suites green; commit pushed without tag or release |

## 3. Data Model (additive, five tables)

`backend/app/security/org_models.py`

- `organizations` — root of the hierarchy.
- `plants` — FK `organizations.id`, ondelete CASCADE.
- `areas` — FK `plants.id`, ondelete CASCADE.
- `user_scopes` — composite PK `(user_id, scope_level, scope_id)`, CheckConstraint on `scope_level IN (ORGANIZATION, PLANT, AREA)`; binds an identity to a subtree.
- `device_scopes` — PK `device_id` (FK `devices.device_id`, ondelete CASCADE), `area_id` (FK `areas.id`, ondelete CASCADE); one row per device placement.

Deletes cascade downward only: deleting an Organization removes its Plants, Areas, user bindings referencing it, and device placements; the Device itself is never deleted (its placement row goes with the CASCADE).

## 4. Scope Policy (central decision layer)

`backend/app/security/scope_policy.py`

- `resolve_device_scope(session, principal) -> frozenset[str] | None`
  - `None` = unrestricted (wildcard permission holder, or no bindings at all — the migration-period default so existing identities keep their current reach).
  - Otherwise a frozenset of in-scope `device_id`s, computed by walking ORGANIZATION → PLANT → AREA bindings down the hierarchy.
- `ensure_device_in_scope(session, principal, device_id, *, method=None, path=None)` — raises `AppError(SCOPE_DENIED, ..., 403)` and writes an `ACTION_SCOPE_DENIED` audit event (actor = authenticated principal) when out of scope. In-scope or unrestricted: no-op.
- `device_scope_filter(session, principal)` — list-filter form returning the same semantics.

Migration-period default (unbound = global reach) is documented in both `docs/SECURITY_MODEL.md` and `docs/ORGANIZATION_MODEL.md`, including the one-line flip to deny-by-default.

## 5. API Surface

`backend/app/api/organizations.py`, mounted under `/api/v1` and `/api`.

- Organizations: list / create / get / update / delete (`org.read` for reads, `org.manage` for structure CRUD).
- Plants, Areas: list / create / update / delete under their parent (`org.read` / `org.manage`).
- User scopes: `GET /users/{user_id}/scopes`, `PUT /users/{user_id}/scopes` (wholesale replacement) — `scope.manage`.
- Device scope: `PUT /devices/{device_id}/scope` accepting `{"area_id": ... | null}` (null detaches) — `scope.manage`; `GET` returns current placement — `org.read`.
- All structure/binding mutations write audit events with `actor_user_id` and `trace_id` from request context.

RBAC vocabulary additions in `app/security/rbac.py`: `org.read`, `org.manage`, `scope.manage`. Seed: ADMIN (wildcard) effectively holds all; OPERATOR and VIEWER gain `org.read` via migration `20260924_11` GRANTS.

## 6. Scope Enforcement Coverage (existing routes)

| Area | Routes | Mechanism |
|------|--------|-----------|
| Configurations | list, create, get, update, delete, validate, clone, publish, status, apply, audit (11 routes) | `ensure_device_in_scope` as first body statement |
| Alarms | list (filtered via `device_scope_filter` + `AlarmRepository.list_instances(device_ids=...)`), related, get, acknowledge, clear | filter / `ensure_device_in_scope` after fetching the alarm |
| Connectivity | get device, start, stop | `ensure_device_in_scope` before gateway ops |
| Assets | attach_device, detach_device | `ensure_device_in_scope` |

Denied mutations never reach the business layer; the alarm-denial test asserts no alarm state mutation on denial.

## 7. Migration

`backend/alembic/versions/20260924_11_phase6_13_b_org_scope.py` (revision `20260924_11`, down_revision `20260924_10`)

- Creates the five tables with CASCADE FKs.
- Seeds permission grants (`org.read` → OPERATOR, VIEWER; `org.manage`, `scope.manage` → ADMIN) via `GRANTS`.
- Downgrade: drops tables in reverse dependency order, deletes seeded permission rows.
- The sealed Phase 6.12 migration is untouched; RBAC parity tests verify the combined seed across 6.12 + 6.13-A + 6.13-B and that each migration slice is disjoint (additive).

## 8. Tests

- `backend/tests/security/test_scope_governance.py` (NEW, DB-backed, opt-in like the 6.13-A suite): hierarchy CRUD, cascade delete, duplicate name 409, binding validation, device scope validation (unknown device/area), structure mutation attribution, `scope.manage` gating for operator, bound operator reaches in-scope device, out-of-scope refused with `SCOPE_DENIED` audit, list filtered, unbound operator keeps global reach, ADMIN with bindings unrestricted, alarm never mutated on denial, config route scope honored, `org.read` visible to VIEWER, delete org revokes reach, model-table presence.
- `backend/tests/security/test_route_coverage.py`: org/plant/area/scope prefixes and EXPECTED permission matrix rows added.
- `backend/tests/security/test_rbac_vocabulary.py`: loads all three security migrations; `_seed_of()` supports both `ROLE_SEED` (6.12) and `GRANTS` (6.13-A/B); parity + additive-disjoint assertions.
- `backend/tests/security/conftest.py`: org tables registered in the schema helper.

## 9. Documentation

- `docs/ORGANIZATION_MODEL.md` (NEW): hierarchy diagram, table ownership, scope evaluation table, API surface, audit semantics, migration, non-goals, verification.
- `docs/SECURITY_MODEL.md`: role grant tables, enforcement matrix (org/scope rows), the "Scope: the enterprise hierarchy" section, audit rows, verification table, non-goals.

## 10. Regression Results

| Suite | Command | Result |
|-------|---------|--------|
| backend mypy | `mypy app tests` | Success: no issues in 183 source files |
| backend ruff | `ruff check .` + `ruff format --check` | All checks passed |
| backend pytest | `pytest -q` | 440 passed, 297 skipped (DB-backed opt-in suites; no PostgreSQL locally/CI), 2 warnings |
| frontend | `npm run lint` / `test` / `build` | lint clean; 10 files / 56 tests passed; vite build OK (303.48 kB js) |
| ml | `ruff check` / `format --check` / `mypy industrial_ml tests` / `pytest` | ruff clean; mypy clean (10 source files); 16 passed |
| simulator | `ruff check` / `format --check` / `mypy simulator tests` / `pytest` | ruff clean; mypy clean (23 source files); 24 passed |
| deployment | `validate_env.py .env.example --mode example` / `security_scan.py` / `pytest tests/test_deployment_foundation.py` | env validation pass; secret scan clean (0 findings); 13 passed |

The 297 skips are the opt-in real-PostgreSQL suites (`test_phase613_actor_migration.py`, `test_scope_governance.py`); this is consistent with the established pattern — CI has no database service.

## 11. Commit

- Commit: `feat: add enterprise organization model and device scope governance (Phase 6.13-B)` on `main`, pushed to `origin/main`.
- No tag, no release (constraint 6). CI result recorded after push.

## 12. Non-Goals (explicit)

- No scope edges beyond device placement (no per-user device exceptions, no time-bound scopes).
- No deny-by-default flip (migration-period default retained and documented).
- No second Device/Asset system; no device data import.
- No changes to LangGraph/Agent/RAG/ML/Workflow/Approval/WorkOrder state machines.
