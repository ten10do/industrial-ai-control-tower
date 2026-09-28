# PHASE_6_13_D_COMPLETE_REPORT

Phase 6.13-D — Governance Enforcement Hardening

Status: COMPLETE (full regression green on real PostgreSQL, committed to `main`, pushed to `origin/main`, no tag / no release)

Commits on `main`:

- `dc611c9` — feat: governance enforcement hardening (Phase 6.13-D)
- `bf7e95a` — fix: seed migrations read result rows explicitly, not as a mapping
- `c2e2439` — fix: align the org-scope schema with its models
- `37297ad` — fix: make the DB-backed suites survive their first real run
- docs commit — this report

CI: run `36386074435` on `main` — all seven jobs green (backend, frontend, ml, simulator, deployment, docs, security-integration). Earlier runs on this phase failed honestly (migration-gate `dict(rows)` trap, schema drift, then the DB-backed suite defects in §6) and were fixed, not bypassed.

## 1. Objective

Harden the governance and scope layers delivered in 6.13-A/B/C so the platform fails closed instead of accidentally open, and so CI proves the claims on a real PostgreSQL instead of trusting skipped suites. Four sub-phases, no new business features, no new migration.

## 2. Constraint Compliance

| # | Constraint | Compliance |
|---|-----------|------------|
| 1 | D1: DB-backed Security CI | PASS — `security-integration` job runs `pgvector/pgvector:pg16` service with `pg_isready` gate; Migration Gate (upgrade head → current → check, head read from `ScriptDirectory`, never hardcoded); `tests/security` and the alarm/assetconfig/observability suites run on real PostgreSQL with a 0-skip guard (`TEST_DATABASE_URL is not configured` fails the job) |
| 2 | D2: scope deny-by-default | PASS — explicit `ScopeAccessMode` (`UNRESTRICTED` / `SCOPED` / `DENIED`); `UNRESTRICTED` comes only from a real RBAC wildcard; an identity with no bindings gets `403 SCOPE_DENIED`; organization read boundary filters list routes and 403s detail routes; `scripts/check_scope_readiness.py` lists unbound identities pre-deployment |
| 3 | D3: governance fail-closed | PASS — the `session=None → allowed` compatibility branch is gone; a DB failure during policy evaluation returns `503 GOVERNANCE_UNAVAILABLE`; a malformed stored policy is counted (`governance_invalid_policy_total`) and visible on the compliance dashboard (`policies.invalid`), never silent; `/ready` integrates migration-currency and governance-table probes into the bounded-retry database check |
| 4 | D4: invariant verification | PASS — mutation-route invariant (every POST/PUT/PATCH/DELETE carries a permission or sits on the explicit `EXPLICITLY_UNGOVERNED_MUTATIONS` list, including the `/api` auth mirror); scope invariant matrix across alarms/configurations/connectivity/assets/organizations/plants/areas; actor invariant (`actor_user_id` NOT NULL enforced); wildcard-cannot-bypass-DENY test; no-mutation-on-denial tests |
| 5 | Reuse `*_TEST_DATABASE_URL` variables | PASS — no new env var; the three existing names are consumed as-is |
| 6 | No new business functionality / no new migration | PASS — the three migration edits in this phase repaired the phase's own migrations (result-row unpacking, missing `updated_at` columns, missing index declaration), they added no new revision |
| 7 | Fresh venv dependency consistency | PASS — fresh venv install + backend suite green (verified during the implementation commit) |
| 8 | GitHub Actions all green | PASS — run `36386074435` |
| 9 | No force push / no history rewrite | PASS — five forward-only commits on `main` |
| 10 | Non-goals (Kubernetes, SSO, new audit system, 6.14) respected | PASS — none attempted; no tag or release created |

## 3. Production Changes

- `backend/app/security/scope_policy.py` — rewritten around the explicit `ScopeAccessMode` state machine; `resolve_device_access` (wildcard → UNRESTRICTED, no bindings → DENIED), `resolve_organization_access` (bound subtrees plus ancestors and descendants), `ensure_organization_visible` (audit-then-raise), `device_scope_filter` semantics documented (`None` = wildcard only).
- `backend/app/security/policy_engine.py` — fail-closed evaluation; structured invalid-policy warnings with metrics; `GOVERNANCE_UNAVAILABLE` 503 path.
- `backend/app/security/readiness.py` (NEW) — seven governance tables, expected migration head from `ScriptDirectory`, `security_readiness()` probe.
- `backend/app/main.py` — `/ready` merges the security probe into the bounded-retry database check; `ready_state` reports it.
- `backend/app/api/devices.py` — device mutations require `asset.manage`.
- `backend/app/api/organizations.py` — list routes filter by scope, detail routes 403 `SCOPE_DENIED` with an audited event.
- `backend/app/api/governance.py` — dashboard reports `policies.invalid`.
- `backend/app/platform_observability/metrics.py` — five label-free counters (`security_permission_denied_total`, `security_scope_denied_total`, `governance_policy_denied_total`, `governance_evaluation_error_total`, `governance_invalid_policy_total`).
- `scripts/check_scope_readiness.py` (NEW) — read-only migration tool; exits non-zero with `{"status": "fail", "unbound_users": [...]}`.
- `backend/app/security/scope_policy.py` (follow-up `37297ad`) — real bug found by the CI gate: an AREA binding resolves upward to its plant, but the plant → organization pass ran before the area pass, so an AREA-bound caller could not see its own organization. Order fixed; covered by `test_a_bound_operator_sees_only_the_hierarchy_it_is_bound_to`.

## 4. Migration Repairs (no new revision)

- `20260924_10/11/12` — `dict(rows)` on a `CursorResult` takes the `.keys()` mapping path and dies on subscript; the three seed migrations now unpack rows explicitly.
- `20260924_11` — `user_scopes` / `device_scopes` create the `updated_at` columns the models declare; `DeviceScope` declares `ix_device_scopes_area_id` so `alembic check` reports no drift.

## 5. CI Workflow

`.github/workflows/ci.yml` — `security-integration` job:

1. `pgvector/pgvector:pg16` service, `pg_isready` health gate.
2. The three `*_TEST_DATABASE_URL` env vars exported.
3. Migration Gate: `upgrade head` → `current` → `check`, plus a `current == head` assertion.
4. `pytest tests/security -q -rs` with FAILED/ERROR guard and a 0-skip guard.
5. `pytest tests/incidents tests/assetconfig tests/test_observability_integration.py -q -rs` with the same guards.

## 6. What the First Real Run Exposed (follow-up `37297ad`)

The DB-backed suites had never actually executed against PostgreSQL; switching them on surfaced defects that skipped runs cannot. All were fixed at the root, none by loosening an assertion:

| Defect | Fix |
|---|---|
| `test_governance.py` logged in as 23 `gov.*` identities that were never registered → `INVALID_CREDENTIALS` | autouse fixture registers the identity set (with correct roles) after the per-test truncate |
| assetconfig / incidents conftests did not create `governance_policies` → fail-closed engine answered `503 GOVERNANCE_UNAVAILABLE` | governance tables added to both schema helpers with the fail-closed rationale documented |
| Alarm seed rows inserted before their device master row → FK violation (the string FK is invisible to the unit of work) | explicit `flush()` of the parent row; scope-suite `seed_alarm` now ensures the device exists |
| 6.13-A attribution tests assumed unbound operators have global reach, denied under 6.13-D | `grant_reach` helper provisions admin → org → plant → area → device assignment → user binding before exercising attribution |
| AREA-bound callers saw an empty organization list | production fix, §3 last bullet |
| Alarm `clear` requires `reason`; the cascade test sent `{}` → 422 | the request now carries the reason |
| Plant-cascade test asserted 404 on `GET /areas/{id}`, a path with no read route → 405 | cascade proven at the database, where the ON DELETE rule lives |
| assetconfig audit assertion assumed oldest-first order; the trail is newest-first | second draft event selected explicitly by `config_version` |

## 7. Verification Evidence

Local (portable PostgreSQL 16.15.0, Windows, working venv):

- Full DB-backed regression `tests/security + tests/incidents + tests/assetconfig`: **543 passed, 1 skipped** (the pg_dump round-trip skip is environmental, not a missing-database skip), **0 failed**, 50m47s.
- Earlier full run including the observability integration suite matched CI behavior; the local error there is the portable cluster lacking the pgvector extension, which the CI service image provides.
- Non-DB backend suite: **443 passed, 324 skipped** (all skips are DB suites without their env vars, by design), 45s.
- `ruff check` and `ruff format --check` clean on every touched file.

CI (run `36386074435`, commit `37297ad`):

| Job | Conclusion |
|---|---|
| backend | success |
| frontend | success |
| ml | success |
| simulator | success |
| deployment | success |
| docs | success |
| security-integration | success |

## 8. Documentation Updated

- `docs/SECURITY_MODEL.md` — deny-by-default table, fail-closed matrix, invariants, readiness, metrics.
- `docs/ORGANIZATION_MODEL.md` — `ScopeAccessMode` semantics, organization read boundary, `check_scope_readiness.py` usage.
- `docs/GOVERNANCE_MODEL.md` — fail-closed evaluation semantics, `policies.invalid` on the dashboard.

## 9. Remaining Known Limits (honest, non-blocking)

- The compliance dashboard's `policies.invalid` counts malformed condition shapes detected at evaluation time; a malformed rule that is never evaluated is counted only after a request touches its permission.
- `check_scope_readiness.py` is advisory: it reports unbound identities, it cannot migrate bindings on the operator's behalf.
- The local Windows portable PostgreSQL cannot load pgvector, so the observability integration suite remains CI-only evidence locally.
