# PHASE_6_13_C_COMPLETE_REPORT

Phase 6.13-C — Enterprise Governance & Compliance Layer

Status: COMPLETE (full regression green, committed to `main`, pushed to `origin/main`, no tag / no release)

Commit: `e0ca7be feat: add enterprise governance and compliance layer (Phase 6.13-C)`; follow-up pins `ad89c58`, `15a0b2b` (SQLAlchemy `<2.1` — see §8).

CI: run `36369617064` on `main` — all jobs green (backend, frontend, ml, simulator, deployment, docs).

## 1. Objective

Add enterprise governance on top of the Phase 6.12 Authentication + RBAC foundation, the Phase 6.13-A authenticated-actor migration, and the Phase 6.13-B organization/scope model, without touching the LangGraph / Agent / RAG / ML / Workflow / Approval / WorkOrder state machines and without introducing a second Device/Asset/Audit system.

Delivered capabilities:

1. Audit Governance query capability
2. Change Management basics (ledger + lifecycle state machine)
3. Governance Policy Engine (conditional DENY above RBAC)
4. Compliance Dashboard (read-only aggregates)
5. Security Event audit enhancement (security-boundary slice + aggregation)

## 2. Constraint Compliance

| # | Constraint | Compliance |
|---|-----------|------------|
| 1 | No modification of LangGraph/Agent/RAG/ML/Workflow/Approval/WorkOrder | PASS — zero edits outside security/API/audit/docs/tests; change records never perform or approve changes |
| 2 | No second Device/Asset/Audit system | PASS — governance reads the one `audit_events` table through new read methods on `AuditRepository`; `governance_policies` and `change_records` reference no device/asset data |
| 3 | All permission decisions through the unified Policy Layer | PASS — single enforcement point `require_permission`: RBAC first, then the governance Policy Engine (`app/security/policy_engine.py`); no route consults `governance_policies` directly |
| 4 | All mutations by the authenticated actor | PASS — every governance mutation writes audit through `AuditRepository.add` with `actor_user_id` from the `SecurityContext`; policy refusals are audited as `POLICY_DENIED` with the acting identity before the 403 |
| 5 | Migration downgradeable | PASS — `20260924_12` downgrade drops the two tables in reverse order and deletes exactly the five seeded permission rows |
| 6 | Full regression, no tag/release | PASS — all suites green; pushed without tag or release |

## 3. Data Model (additive, two tables)

`backend/app/security/governance_models.py`

- `governance_policies` — conditional DENY rules: `name` (unique), `effect` (CHECK: only `DENY`), `permission`, `conditions` (JSONB), `enabled`. A policy never grants; removing the governance layer always leaves exactly the RBAC answer.
- `change_records` — the change-management ledger: `title`, `change_type` (CONFIGURATION/HARDWARE/PROCEDURE), `risk_level` (LOW/MEDIUM/HIGH), `status` (DRAFT → SCHEDULED → IN_PROGRESS → COMPLETED, CANCELLED from DRAFT/SCHEDULED/IN_PROGRESS), execution window with CHECK `end > start`, `requested_by_user_id` as an immutable audit-trail reference (no FK, so deleting an identity cannot erase who asked).

Migration `backend/alembic/versions/20260924_12_phase6_13_c_governance.py` (revision `20260924_12`, down_revision `20260924_11`): creates both tables and seeds five permission rows (`governance.manage` → ADMIN; `audit.read`, `governance.read`, `change.read`, `change.manage` → OPERATOR; `governance.read`, `change.read` → VIEWER). No existing table is altered.

## 4. Policy Engine

`backend/app/security/policy_engine.py` — evaluation is centralized; `require_permission` (`app/security/dependencies.py`) asks RBAC first and the Policy Engine second, so every governed route in the platform inherits policy evaluation without a per-route edit.

Conditions (JSONB, AND composition, deliberately few):

| Condition | Matches when |
|---|---|
| `{"always": true}` | Every request — the change freeze; binds everyone including ADMIN, because governance sits above RBAC |
| `{"roles": [...]}` | The caller holds any listed role |
| `{"time_window": {"days": [1..7], "start": "HH:MM", "end": "HH:MM"}}` | Request inside the UTC window (ISO weekdays, Monday=1); a window whose end precedes its start wraps midnight |

Failure semantics: an unknown condition key is rejected at write time (422 `POLICY_CONDITION_INVALID`) and a rule edited out-of-band into an unsupported shape is inert at evaluation time, never fatal — a malformed rule must not turn governed routes into 500s. A refusal is `403 POLICY_DENIED`, audited (`action=POLICY_DENIED`, `status=DENIED`) with policy name, permission, method, path, and acting identity before the 403 is raised. `session=None` (only reachable through dependency stubs, never in production) evaluates as policy-free with an explicit code comment.

## 5. API Surface

`backend/app/api/governance.py`, mounted under both `/api/v1` and `/api`:

| Capability | Routes | Permission |
|---|---|---|
| Audit governance | `GET /governance/audit` (paged, filtered: actor/action/resource/status/trace_id/since/until) | `audit.read` |
| Security events | `GET /governance/security-events` (security-boundary slice + `action`×`status` aggregation) | `audit.read` |
| Compliance dashboard | `GET /governance/compliance/dashboard?window_days=1..90` | `governance.read` |
| Policy register | `GET/POST /governance/policies`, `GET/PATCH/DELETE /governance/policies/{id}`, `POST /governance/policies/evaluate` (what-if, changes nothing) | `governance.read` / `governance.manage` |
| Change management | `GET/POST /governance/changes`, `GET/PATCH /governance/changes/{id}` (DRAFT-only edits), `POST /governance/changes/{id}/transition` (state machine; scheduling requires an execution window) | `change.read` / `change.manage` |

Audit query read side lives on the one `AuditRepository` (`query`, `summary`, `AuditQueryFilters`, `MAX_QUERY_LIMIT=200`); the incident timeline keeps its own oldest-first query untouched. Every governance mutation is attributed to the authenticated caller with `trace_id`. The dashboard computes everything from `audit_events`, `governance_policies`, `change_records`, and `users` at request time — no cache or copy can drift from the evidence.

## 6. Tests

- `backend/tests/security/test_governance.py` (NEW, DB-backed, opt-in): condition matcher (pure functions), policy CRUD gating/validation, evaluate endpoint, enforcement above RBAC with audited evidence, `always` freeze binding ADMIN, inert malformed rule, change lifecycle state machine, scheduling window rules, draft-only edits, attribution, audit queries, security-event slice, dashboard aggregates.
- `backend/tests/security/test_rbac_vocabulary.py`: loads all four security migrations; parity + additive-disjoint assertions extended to `20260924_12`; new grant-split test.
- `backend/tests/security/test_route_coverage.py`: governance prefixes added to `GOVERNED_PREFIXES` (`/api/v1/governance`, `/api/governance`) and 14 EXPECTED matrix rows added.
- `backend/tests/test_control_tower_queries.py`: `FakeSession` answers governance queries with "no policies" without consuming queued results.
- `backend/tests/security/conftest.py`: governance tables registered in the schema helper.

## 7. Documentation

- `docs/GOVERNANCE_MODEL.md` (NEW): full governance model.
- `docs/SECURITY_MODEL.md`: role grant tables, enforcement matrix, "Governance: policy above RBAC" section.

## 8. Regression Results

| Suite | Command | Result |
|-------|---------|--------|
| backend mypy | `mypy app tests` | Success: no issues in 187 source files |
| backend ruff | `ruff check .` + `ruff format --check` | All checks passed; 210 files formatted |
| backend pytest | `pytest -q` | 447 passed, 310 skipped, 0 failed |
| frontend | `npm run lint` / `test` / `build` | lint clean; 10 files / 56 tests passed; vite build OK (303.48 kB js) |
| ml | `ruff check` / `format --check` / `mypy industrial_ml tests` / `pytest` | ruff clean; mypy clean (10 source files); 16 passed |
| simulator | `ruff check` / `format --check` / `mypy simulator tests` / `pytest` | ruff clean; mypy clean (23 source files); 24 passed |
| deployment | `validate_env.py .env.example --mode example` / `security_scan.py` / `pytest tests/test_deployment_foundation.py` | env validation pass; secret scan clean (0 findings); 13 passed |

Environment note: the backend/.venv was found corrupted (missing modules across pytest/pydantic/httpx/jose/passlib/mypy) and was quarantined as `backend/.venv-broken-20260928` and rebuilt from `pyproject.toml [dev]` with SQLAlchemy pinned to 2.0.54 and FastAPI 0.141.1 to match the codebase baseline; the ml/.venv was repaired in place (certifi/greenlet/distro). The 310 skips are the opt-in real-PostgreSQL suites (`test_phase613_actor_migration.py`, `test_scope_governance.py`, `test_governance.py`), consistent with the established pattern — no Docker daemon or PostgreSQL is available locally. CI result recorded after push.

Dependency-pin note: the first CI run failed type check because `SQLAlchemy>=2.0.30` resolved to the newly released 2.1.1, whose `Select` generic signature and `session.get()` typing changes break the existing repositories' annotations. `SQLAlchemy[asyncio]>=2.0.30,<2.1` was pinned in both `backend/requirements.txt` (`ad89c58`) and `backend/pyproject.toml` (`15a0b2b`); CI then went fully green.

## 9. Non-Goals (explicit)

- No policy effect other than DENY; no per-user policy exceptions.
- No scope edges beyond those of Phase 6.13-B; no deny-by-default flip.
- No second Device/Asset/Audit system; no audit data import or export surface.
- No changes to LangGraph/Agent/RAG/ML/Workflow/Approval/WorkOrder state machines.
- No tag, no release.
