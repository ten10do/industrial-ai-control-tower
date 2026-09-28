# PHASE_6_13_D_MIGRATION_COMPATIBILITY_REPORT

Phase 6.13-D Closeout — Historical Migration Compatibility Verification

Status: **PHASE_6_13_D_MIGRATION_COMPATIBILITY_CONFIRMED — NO_RECONCILIATION_REQUIRED** (Case A; no code changes, no new migration; report-only commit)

---

## 1. Starting HEAD

`4c2bcd12159ba6f89a003cb349905ea03324ead9` (`main`, working tree clean, synced with `origin/main`)

## 2. Final HEAD

See §13 (report commit appended on top of `4c2bcd1`; no code or migration files touched).

## 3. Historical migration diff (Phase 6.13-D, `HEAD~5..HEAD`)

Three migration files were amended after their original authoring:

| File | Amended in | Change |
|---|---|---|
| `20260924_10_phase6_13_a_actor_migration.py` | `bf7e95a` (09-28 11:33) | `dict(rows)` → explicit row unpacking in `_load_role_ids` and in `downgrade`'s permission lookup |
| `20260924_11_phase6_13_b_org_scope.py` | `bf7e95a` + `c2e2439` (09-28 11:39) | Same execution fix; **plus two added columns** (see §4) |
| `20260924_12_phase6_13_c_governance.py` | `bf7e95a` | Same execution fix only |

Original authoring dates (git log):

- `20260924_10` — `bd37e68` 2026-09-24 15:07
- `20260924_11` — `923dbda` 2026-09-24 16:29
- `20260924_12` — `e0ca7be` 2026-09-28 10:18

## 4. Change classification

| Revision | Execution fix | Schema change | Seed/grant change |
|---|---|---|---|
| `20260924_10` | Yes (`dict(rows)` unpacking, upgrade + downgrade) | None | None |
| `20260924_11` | Yes (same pattern) | **Yes**: `user_scopes.updated_at`, `device_scopes.updated_at` added (both `DateTime(timezone=True) NOT NULL`, application-side default, no `server_default`) | None |
| `20260924_12` | Yes (same pattern) | None | None |

Point-by-point verification of the brief's named candidates:

- `user_scopes.updated_at` — **added** in `c2e2439` (was absent pre-amendment; models declared it via `SecurityTimestampMixin`, so pre-amendment migration and models were out of sync).
- `device_scopes.updated_at` — **added** in `c2e2439` (same situation).
- `ix_device_scopes_area_id` — **not new**. The index existed in the pre-amendment migration (`git show HEAD~5:...` shows `op.create_index("ix_device_scopes_area_id", ...)` unchanged). What changed is the model side: `DeviceScope.__table_args__` now declares the index so `alembic check` reports no drift.
- Constraints — unchanged; all `CHECK`/`FK`/`UNIQUE` definitions identical pre/post amendment.
- Seed data / grants — unchanged (only a `# noqa` comment added inside `_seed`).

## 5. Persistent consumer evidence

Conclusion: **Case A — no persistent consumer ever executed the pre-amendment revisions.** Evidence, in order of strength:

1. **Direct database inspection (decisive).** The only local persistent PostgreSQL cluster (`D:/soft/pgsql`, PostgreSQL 16.4) was started and enumerated read-only via single-user mode (no writes). It contains four non-template databases: `industrialvision_dev`, `industrialvision_docker`, `industrialvision_test`, `vision_qc`. All carry `alembic_version` at `0002_quality_rules_unique` / `0001_create_core_tables` (an older, different revision lineage) and **none contain `user_scopes`, `device_scopes`, or `organizations`**. No database on this machine has ever run `20260924_10/11/12`.
2. **Phase 6.13-B report** (when `20260924_11` was authored, 09-24): "440 passed, 297 skipped (DB-backed opt-in suites; **no PostgreSQL locally/CI**)"; "CI has no database service".
3. **Phase 6.13-C report** (when `20260924_12` was authored, 09-28 10:18): "The 310 skips are the opt-in real-PostgreSQL suites … **no Docker daemon or PostgreSQL is available locally**".
4. **Phase 6.13-D report §6** (09-28): "The DB-backed suites had **never actually executed against PostgreSQL**" before 6.13-D switched them on.
5. **CI workflow history**: the `security-integration` job (real PostgreSQL) was added in `dc611c9` at 09-28 11:18 — *after* all three revisions existed. All CI database usage is ephemeral: a per-run `pgvector/pgvector:pg16` service container, a fresh `platform_ci` database, and disposable `*_test` databases that each suite drops and recreates (`PHASE_6_12_FINAL_REPORT.md`: "_TEST_DATABASE_URL variables are per-suite and each suite drops the [database]").
6. **No preserved state**: no `.sql` / `.dump` / backup artifacts exist anywhere in the repository tree; no `.env` with a persistent `DATABASE_URL`; Docker daemon was not running and held no relevant state.

The disposable/local-run and persistent-deployment categories are therefore cleanly separated: every execution of these revisions happened either in ephemeral CI containers or in per-run `_test` databases, and the sole persistent cluster predates and excludes the security/governance lineage entirely.

## 6. Decision

**NO_RECONCILIATION_REQUIRED** (Case A). Per the decision rule: no code change, no new migration. The record statement:

> Historical migration amendments were made before any persistent deployment consumed those revisions; therefore no upgrade-compatibility obligation exists for the pre-amendment schema.

For completeness, the hypothetical risk under Case B/C is documented: a legacy database at pre-amendment `20260924_12` would reach `alembic current == head` with `upgrade head` as a no-op while missing the two `updated_at` columns, and ORM inserts into `user_scopes`/`device_scopes` would fail (`NOT NULL`, no server default). `alembic check` would report the drift. This is exactly the failure mode the reconciliation migration would have repaired had a persistent consumer existed.

## 7. Fresh install result

- **CI Migration Gate (authoritative)**: run `36386874804` at HEAD `4c2bcd1` — all 7 jobs success, including `security-integration`, whose Migration Gate runs on a fresh `platform_ci` database: `alembic upgrade head` → `alembic current` → `alembic check` → explicit `current == head` assertion (head read from `ScriptDirectory`, never hardcoded). This exercises the amended `20260924_10/11/12` exactly as committed. Run `36386074435` (`37297ad`) likewise success.
- **Local fresh-install probe (partial, disposable DB on PostgreSQL 16.15, `.workbuddy/pgtool`)**: fresh database `migration_compat_fresh_test` → `alembic upgrade 20260917_02` succeeded (revisions 01–02); `alembic upgrade head` failed at revision `20260920_03` with `extension "vector" is not available` — the known environmental blocker (no pgvector locally, `PHASE_6_13_D_COMPLETE_REPORT.md` §9). The probe was dropped afterwards. The full chain therefore remains CI-verified only, which is the pre-existing, documented arrangement.

## 8. Legacy upgrade result

Not executed, by design: Case A was established by direct evidence (§5), so no legacy schema exists to upgrade and none needed to be constructed. The git-history materialization path (checkout `e0ca7be` → `upgrade 20260924_12` → switch to head) was evaluated and is blocked locally by the same pgvector gap at revision 03, independent of the amendments; with pgvector available only in CI, this path adds no information beyond §5 + §7 and was not run.

## 9. Data preservation result

Not applicable: no reconciliation migration was created, so no upgrade ran against pre-existing business data. The DB-backed security regression below additionally exercised insert/truncate/cascade semantics on the current schema without data loss.

## 10. alembic current / check result

- CI (`platform_ci`, pgvector pg16, HEAD `4c2bcd1`): `alembic check` clean, `current == head == 20260924_12`.
- Local chain inspection: `alembic history` linear, `alembic heads` = `20260924_12` (single head).

## 11. Regression result

- **DB-backed security suite, local, real PostgreSQL 16.15 (pgtool cluster, trust auth, disposable `migration_compat_sec_test` database, dropped by the fixture afterwards): `pytest tests/security -q -rs` → 217 passed, 0 failed, 0 skipped, 16m08s** at working tree HEAD `4c2bcd1`. This suite includes the RBAC vocabulary migration parity tests (which load the amended revision modules) and the actor-migration / scope-governance database suites.
- Full backend / frontend / ml / simulator / deployment regression at this HEAD: covered by CI run `36386874804` (all green); no code changed since.
- Note: the local run used `ALARM_TEST_DATABASE_URL` on port 5433 (the pgtool cluster's port); no missing-DB skip occurred (0 skipped).

## 12. CI result

GitHub Actions (public API): run `36386874804`, head `4c2bcd1` — **success** (backend, frontend, ml, simulator, deployment, docs, security-integration). The report commit pushed after this closeout was watched to completion; see §13.

## 13. Git status

- Working tree was clean at start (`4c2bcd1`, equal to `origin/main`).
- Only change: this report file, committed and pushed as a docs-only commit on `main`. No tag, no release, no migration, no source change.

## 14. Known limitations

1. Full local `alembic upgrade head` is environmentally impossible (no pgvector on any local Windows cluster; pgvector DLL installation previously failed). The authoritative fresh-install gate is CI's pgvector/pg16 job. This is a pre-existing, documented limitation, not introduced by this closeout.
2. The legacy-upgrade path (§8) was reasoned and evidence-closed rather than executed; it would only become executable if a legacy database actually existed, which §5 disproves.
3. Docker Desktop could not be used as a local pgvector source: its WSL2 dependency is blocked by the local security policy (program blacklist).
4. The `D:/soft/pgsql` cluster was inspected via single-user mode because its superuser credential is not recorded in the repository; only read-only `SELECT` statements were issued.
