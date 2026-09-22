# Phase 6.8 Final Report: Asset and Device Configuration Management

## 1. Status

**PASS. Awaiting acceptance.** Phase 6.8 is implemented, tested, documented, and reported. No tag and
no release were created. Execution stops here; Phase 6.9, Phase 7, RBAC, Kubernetes, and cloud
infrastructure were not started.

| Item | Value |
|---|---|
| Phase | 6.8 Asset and Device Configuration Management |
| Branch | `main` |
| Alembic revision | `20260922_06` (down_revision `20260922_05`) |
| Backend regression | 312 passed |
| Assetconfig suite | 113 passed (validation 19, assets 14, configuration 39, API 36, integration 5) |
| Gateway suite | 11 passed, including one new bounded-stop regression test |
| Frontend suite | 29 passed (22 baseline + 7 new) |
| Static analysis | Ruff clean, mypy clean (121 source files), ESLint clean, `tsc` clean |
| Frontend build | Vite build clean |
| Docker | backend and frontend rebuilt without cache |
| Migration | Applies from empty to head and downgrades to base on a purpose-built database |
| Tag / Release | None |

## 2. Baseline

The entry point is Phase 6.7, Industrial Protocol Gateway, delivered in commits `b74a1b9`
(`feat: add industrial protocol gateway`) and `926590d` (`docs: add phase 6.7 final report`).

Phase 6.7 gave the platform a declarative onboarding path: a YAML definition document was loaded at
startup, resolved into typed `DeviceDefinition` objects, and handed to `IndustrialProtocolGateway`,
which started one `DeviceRuntime` per device over MQTT, OPC UA, Modbus TCP, or the simulator adapter.
Telemetry flowed through `GatewayIngestionSink` into the single ingestion boundary,
`TelemetryService.ingest_payload`.

Phase 6.7 documented one open item that Phase 6.8 closes: device definitions were configuration-file
driven with no persistence, no version history, and no way to answer which configuration a running
device actually started with.

| Baseline property | Phase 6.7 | Phase 6.8 |
|---|---|---|
| Desired state source | YAML file | Versioned database record |
| Change history | None | Full version chain with lifecycle timestamps |
| Rollback | Edit the file and restart | Republish an archived snapshot as a new version |
| Drift visibility | None | Desired versus applied, with failure cause |
| Reload scope | Full process restart | Single device runtime |
| Device location | Not modelled | SITE → LINE hierarchy |

## 3. Architecture Audit

The audit confirmed the change stayed inside its boundary. Verification was performed against the
working tree, not against intent.

Unchanged:

- `TelemetryService.ingest_payload` remains the only write path into the `telemetry` table.
- The canonical eight-signal contract is untouched.
- ML, RAG, LangGraph workflow, agents, deterministic safety policy, human approval, work-order,
  observability, and gateway reliability paths were not modified in behavior.
- OPC UA and Modbus adapters remain read-only.

Added or extended:

- `backend/app/assetconfig/` holds 11 modules covering contracts, models, repository, service,
  validation, apply, audit, source resolution, and errors.
- `backend/app/api/assets.py` and `backend/app/api/configurations.py` provide the HTTP surface.
- `backend/app/gateway/` gains a database-backed resolution source and a controlled reload entry
  point.
- `backend/alembic/versions/20260922_06_phase6_8_asset_device_configuration.py` adds the schema.
- `frontend/src/pages.tsx` adds `AssetsConfigPage` and its subcomponents.

Boundary statements that the audit verified in code rather than in prose:

| Boundary | Evidence |
|---|---|
| No second device identity | Every configuration row FKs `devices.device_id`; no new device table |
| No PLC or fieldbus write | No write call exists in the adapter or configuration path |
| No secret persistence | The validator rejects non-opaque credential fields |
| No live probe during validation | The validation module imports no socket or protocol client |

## 4. Database

Migration `20260922_06` adds three tables and one column.

| Object | Kind | Purpose |
|---|---|---|
| `asset_nodes` | Table | SITE → LINE hierarchy |
| `devices.asset_node_id` | Column | Nullable FK, `ON DELETE RESTRICT`, indexed |
| `device_configurations` | Table | Immutable version snapshots |
| `device_configuration_runtime_status` | Table | Observed runtime state |

Constraints worth naming:

- `ck_asset_nodes_parent_shape` enforces at the database that `SITE` has no parent and `LINE` has one.
- `uq_device_configurations_device_version` makes `(device_id, version)` unique.
- `ck_device_configurations_published_at` prevents a row from claiming publication without a
  timestamp.
- `uq_device_configurations_single_published` is a partial unique index on `device_id WHERE status =
  'PUBLISHED'`.
- `ck_device_configuration_runtime_apply_status` and `ck_device_configuration_runtime_source` pin the
  two enumerated runtime fields.

A design point that required an explicit fix during implementation: PostgreSQL evaluates a unique
index on every statement, not only at commit. Publishing by promoting the new row before demoting the
incumbent therefore violated the partial index mid-transaction. The service now demotes first, then
promotes, and the demoted row is synchronized through the session with `synchronize_session="fetch"`
so the identity map does not keep reporting it as published.

The migration was verified against a database created for that purpose, not only against the ORM
metadata that the test suites build from. `alembic upgrade head` ran from an empty database through
all six revisions to `20260922_06`, after which introspection confirmed the tables, the four
constraints, the four indexes, and the partial unique index with its `WHERE status = 'PUBLISHED'`
clause. Two behaviours were then probed with direct SQL against that migrated schema:

| Probe | Observed result |
|---|---|
| Insert a second `PUBLISHED` row for one device | Rejected: `duplicate key value violates unique constraint "uq_device_configurations_single_published"` |
| Delete a `SITE` that still has a `LINE` child | Rejected: `violates foreign key constraint "fk_asset_nodes_parent_id"` |
| Insert a `LINE` whose parent is another `LINE` | Accepted by PostgreSQL; see section 5 and Open Item O-5 |

`alembic downgrade base` was then run on the same database and completed through all six revisions,
leaving only `alembic_version`. The migration is reversible, and the verification database was
dropped afterwards.

## 5. Asset Model

The hierarchy is intentionally two levels deep.

```text
SITE (root, parent_id IS NULL)
└── LINE (parent_id → SITE)
    └── DEVICE (reuses devices.asset_node_id)
```

| Rule | Enforcement | Layer |
|---|---|---|
| `SITE` has no parent | Check constraint `ck_asset_nodes_parent_shape` | Database |
| `LINE` requires a parent | Check constraint `ck_asset_nodes_parent_shape` | Database |
| Only `SITE` and `LINE` exist | Check constraint `ck_asset_nodes_type` | Database |
| Parent cannot be deleted while it has children | FK `ON DELETE RESTRICT`, `fk_asset_nodes_parent_id` | Database |
| Node cannot be deleted while a device points at it | FK `ON DELETE RESTRICT`, `ix_devices_asset_node_id` | Database |
| A `LINE` parent must be a `SITE` | Rule `ASSET_PARENT_RULES`, resolved parent's type is compared | Service |
| Depth is capped at two levels | Same rule; no third level is representable | Service |
| Unassigned devices stay visible | `/assets/tree` returns a separate `unassigned_devices` list | API |

Two layers are named explicitly because their guarantees differ, and the difference was measured
rather than assumed. A direct SQL probe against the migrated schema confirmed that the check
constraint validates only the child row's own fields, so a raw `INSERT` of a `LINE` whose parent is
another `LINE` is accepted by PostgreSQL. The service rule closes that path for every request the
product exposes, and cycles remain impossible through the API. The database does not independently
reject a malformed parent type, and this is recorded in Open Items rather than presented as a
database guarantee.

There is no code path that yields an orphaned child. Deleting a node is refused rather than cascading,
because a silent cascade would detach devices from their location without an operator decision. The
refusal was verified by direct SQL: deleting a `SITE` that still had a `LINE` child raised
`fk_asset_nodes_parent_id`.

## 6. Configuration Lifecycle

```text
DRAFT ──validate──▶ VALIDATED ──publish──▶ PUBLISHED ──superseded──▶ ARCHIVED
  ▲                                                                    │
  └────────────────────── clone (new version) ◀────────────────────────┘
```

| Transition | Precondition | Effect |
|---|---|---|
| Create draft | Device exists and is active | New row at `next_version`, status `DRAFT` |
| Update draft | Status is `DRAFT` | Snapshot replaced in place |
| Validate | Status is `DRAFT` or `VALIDATED` | Structured result stored, status `VALIDATED` |
| Publish | Status is `VALIDATED` or `DRAFT` with a passing validation | Status `PUBLISHED`, incumbent archived |
| Clone | Any non-deleted version | New `DRAFT` at `next_version` |
| Archive | Implicit during publish | Status `ARCHIVED`, `archived_at` set |
| Delete | Status is `DRAFT` | Row removed |

Published rows are immutable. There is no update path that writes to a `PUBLISHED` or `ARCHIVED` row;
attempts return `409`. Changing a live device follows clone, edit, validate, publish, so the snapshot
a runtime reported is always reproducible afterwards.

Rollback republishes an archived snapshot as a new version. This keeps the version chain append-only,
so the act of rolling back is itself auditable and the version that was reverted is not erased.

## 7. Source of Truth

The database is the source of truth for desired configuration.

| Situation | Resolved source | Reported `source` |
|---|---|---|
| A published configuration exists | `device_configurations` row | `database` |
| No published row exists | Bootstrap definition | `bootstrap` |

The restart-recovery test enables managed resolution with no definition file present, which proves
the runtime rebuilds from the database. Because `source` is persisted, an operator can distinguish a
database-managed device from a bootstrapped one without inspecting logs.

## 8. Versioning

| Property | Behaviour |
|---|---|
| Numbering | Monotonic per device, starting at 1, unique via `uq_device_configurations_device_version` |
| Prior versions | Retained; publishing archives rather than deletes |
| Immutability | No write path targets a non-draft row |
| Snapshot content | Full typed `DeviceDefinition` as JSONB, reused verbatim from Phase 6.7 |
| Reconstruction | Any stored snapshot parses back into the exact typed object the gateway consumes |

Reusing the Phase 6.7 `DeviceDefinition` avoids the failure mode where a stored configuration passes
a storage-specific schema and then diverges from the runtime's own model. A payload that fails the
typed validator cannot reach the database, because every write path parses before persisting.

## 9. Desired versus Applied

Desired and applied state live in `device_configuration_runtime_status`, separate from the immutable
snapshots.

| Field | Meaning |
|---|---|
| `desired_version` | Published version, from `device_configurations` |
| `applied_version` | Version the running gateway actually started |
| `apply_status` | `PENDING` / `APPLYING` / `APPLIED` / `FAILED` |
| `source` | `database` / `bootstrap` / `none` |
| `last_apply_at` | Timestamp of the last attempt |
| `last_apply_error` | Cause when the attempt failed |
| `in_sync` | True only when applied equals desired and the last attempt succeeded |

Separation is a correctness requirement. Desired and applied values change while the system runs,
whereas a snapshot must remain exactly as approved. Storing runtime state on the snapshot would mutate
evidence after the fact.

The API reports publication and application independently. A successful publish that failed to apply
returns the published version with `in_sync = false` and a populated `last_apply_error`.

## 10. Runtime Reload

Reload is scoped to a single device.

| Property | Implementation |
|---|---|
| Scope | The target device's runtime only |
| Isolation | Every other runtime keeps its poll loop and connection |
| Ordering | New definition is constructed and validated before the live runtime is replaced |
| Transient state | `APPLYING` is committed before the runtime is touched |
| Failure behaviour | The previous runtime keeps polling; drift is recorded |
| Stop behaviour | Bounded, so a row that refuses to observe cancellation cannot stall the reload |
| Retry | `POST /configuration/apply` reattempts the published version |

The transient `APPLYING` state is committed before the runtime is changed so that a process crash
mid-apply leaves an honest intermediate state rather than a stale `APPLIED`. A raising applier is
converted into a failed apply outcome; a malformed version cannot produce a 500 and cannot take a
healthy runtime down.

## 11. Failure Evidence

| Scenario | Expected outcome | Verified by |
|---|---|---|
| Applier raises | `apply_status = FAILED`, `last_apply_error` populated, request succeeds with drift | `test_a_raising_applier_is_reported_as_drift_not_an_internal_error` |
| Bad version published against a healthy runtime | Healthy device keeps producing telemetry | `test_a_bad_version_cannot_take_a_healthy_runtime_down` |
| Applier unavailable | HTTP `503`, no fabricated success | API suite, unavailable-applier test |
| Healthy device reloaded alongside a failure | Unaffected device keeps polling | `test_reloading_one_device_leaves_the_other_untouched` |
| Applying in progress | `APPLYING` observable while the runtime is reconfigured | `test_applying_state_is_visible_while_the_runtime_is_reconfigured` |
| Publish with no runtime owner | `PENDING` reported, not `APPLIED` | `test_publish_without_a_runtime_owner_reports_pending` |
| A runtime that refuses to observe cancellation | `stop` returns inside its deadline, device reports `STOPPED`, adapter released | `test_stop_is_bounded_when_a_read_refuses_cancellation` |

No test asserts a success that the system does not produce. Where a behaviour could not be made
successful, the test asserts the honest failure state instead of relaxing the assertion.

## 12. Restart Recovery

On startup, a managed device resolves its definition from the published database row. The recovery
test runs with managed resolution enabled and no definition file available, then asserts that
telemetry reaches PostgreSQL. Because no file exists to fall back on, a passing test demonstrates
that the database supplied the definition.

`source = database` is persisted, so after a restart an operator can confirm which devices came from
the database and which came from a bootstrap definition.

## 13. API

Both `/api/v1` and `/api` prefixes are registered for every Phase 6.8 router, matching the existing
convention. Both are exercised in the API tests.

Assets:

| Method | Path |
|---|---|
| `GET` | `/assets` |
| `GET` | `/assets/tree` |
| `POST` | `/assets` |
| `GET` | `/assets/{asset_id}` |
| `DELETE` | `/assets/{asset_id}` |
| `PUT` | `/assets/{asset_id}/devices/{device_id}` |
| `DELETE` | `/assets/{asset_id}/devices/{device_id}` |

Configurations:

| Method | Path |
|---|---|
| `GET` | `/devices/{device_id}/configurations` |
| `POST` | `/devices/{device_id}/configurations` |
| `GET` | `/devices/{device_id}/configurations/{version}` |
| `PATCH` | `/devices/{device_id}/configurations/{version}` |
| `DELETE` | `/devices/{device_id}/configurations/{version}` |
| `POST` | `/devices/{device_id}/configurations/{version}/validate` |
| `POST` | `/devices/{device_id}/configurations/{version}/clone` |
| `POST` | `/devices/{device_id}/configurations/{version}/publish` |
| `GET` | `/devices/{device_id}/configuration/status` |
| `POST` | `/devices/{device_id}/configuration/apply` |
| `GET` | `/devices/{device_id}/configuration/audit` |

Status semantics: `404` for unknown device, version, or asset node; `409` for illegal lifecycle
transitions; `422` for validation failure with structured `details.errors`; `503` for an unavailable
applier. The OpenAPI document is asserted in the API suite to contain the full surface.

## 14. Frontend

The `/assets-config` route adds an `Assets & Config` navigation entry and a `configuration`
dependency badge.

| Capability | Detail |
|---|---|
| Hierarchy view | Site and line tree with devices grouped under their line |
| Unassigned section | Devices with no location are shown explicitly |
| Status per device | Protocol, published version, applied version, apply status as text and shape |
| Drift banner | Shown when applied differs from desired or the last apply failed, naming the cause |
| Editor | Raw JSON snapshot with create, save, validate, publish, clone, delete |
| Version history | Lifecycle timestamps per version |
| Audit | Newest first |
| Attach and detach | Move a device between lines |

A real usability defect was found and fixed during this phase. Publish, validate, clone, delete, and
retry-apply were gated behind parsing the editor textarea, so acting on an already-stored version
with an untouched editor did nothing. These actions now operate on the stored version directly.

The page states that device identity comes from the existing registry and that publishing changes
acquisition settings only, not control of the equipment.

## 15. Audit

Configuration lifecycle events are written to the existing `audit_events` table through the existing
`AuditRepository` writer. No second audit table was introduced.

| Property | Value |
|---|---|
| Recorded events | Create, update, validate, publish, clone, delete, apply attempt, apply failure |
| Fields | Device, event type, configuration version, actor, status, timestamp, summary |
| Secrets | None; no credential value is written |
| Actor | Optional header; defaults to the system identity; `system` and null are permitted |
| Ordering | Newest first, asserted in the API suite |
| RBAC | None in this phase, by specification |

## 16. Security

| Property | Guarantee |
|---|---|
| Device identity | Unchanged; `devices.device_id` remains the only identity source |
| Control path | No PLC, Modbus, or OPC UA write; no actuation |
| Secrets | Opaque `secret_ref` / `credential_ref` only; plaintext rejected by validation |
| Validation | Side-effect free; no socket, no probe, no write |
| Published rows | Immutable; changes require a new version |
| Audit | No secret value persisted |
| Adapters | OPC UA and Modbus TCP remain read-only |

## 17. Tests

| Suite | Tests | Coverage |
|---|---|---|
| `tests/assetconfig/test_validation.py` | 19 | Typed validation, signal coverage, secret rejection, side-effect freedom |
| `tests/assetconfig/test_assets.py` | 14 | Hierarchy rules, parent constraints, delete refusal, attach and detach |
| `tests/assetconfig/test_configuration.py` | 39 | Lifecycle, immutability, single published, apply states, raise-safe apply |
| `tests/assetconfig/test_api.py` | 36 | Full HTTP surface, status codes, dual prefixes, audit ordering |
| `tests/assetconfig/test_integration.py` | 5 | Published config → gateway → simulator → PostgreSQL telemetry |
| `tests/gateway/test_gateway.py` | 11 | Inventory, lifecycle, isolation, and the new bounded-stop regression |
| **Backend subtotal** | **114** | |
| `frontend/src/assetsconfig.test.tsx` | 7 | Hierarchy, drift honesty, editor workflow, refusal states |

The integration suite uses the real chain. A configuration is published into PostgreSQL, resolved
through `resolve_definitions(managed=True)`, handed to `IndustrialProtocolGateway` and `DeviceRuntime`,
connected to real Modbus and OPC UA simulator servers, ingested through `GatewayIngestionSink` into
`TelemetryService.ingest_payload`, and asserted as rows in the `telemetry` table. No layer is mocked
except Redis, which is replaced by a fake cache that mirrors the Lua set-if-newer semantics.

Test isolation is guarded: `ASSETCONFIG_TEST_DATABASE_URL` must match a `_test` naming pattern before
the suite will create or drop a database.

## 18. Regression

| Suite | Result |
|---|---|
| Backend (`pytest`) | 312 passed |
| Frontend (`npm test`) | 29 passed |
| Frontend `tsc -b` | Clean |
| Frontend `npm run lint` | Clean |
| Frontend `npm run build` | Clean |
| Ruff | All checks passed |
| mypy | Success, no issues in 121 source files |
| Docker rebuild | backend and frontend rebuilt without cache |

The Docker rebuild used `--no-cache`, so no layer was reused from a previous build. The frontend image
runs `tsc -b && vite build` in its build stage and reported a successful build, which means the type
check and the production bundle both ran inside the container rather than being inferred from the host
run. The backend image was rebuilt without cache a second time after `runtime.py` changed, so the image
matches the fixed source rather than the pre-fix source. The resulting images were
`industrial-ai-control-tower-backend:latest` and
`industrial-ai-control-tower-frontend:latest`. `frontend/.dockerignore` excludes `node_modules`,
`dist`, Vite caches, and the TypeScript incremental build cache, so a stale host artifact cannot mask
a broken build inside the image.

The backend suite grew from 267 to 312 with the 45 Phase 6.8 tests registered through the suite. The
frontend suite grew from 22 to 29. The green backend run took 54.13s, which is worth recording next to
the sixteen minute wedge described below, because the duration alone distinguishes a healthy run from
a stalled one.

Two warnings are emitted and neither is a test problem. One is a `DeprecationWarning` from
`starlette.testclient` about the `anyio.abc.BlockingPortal` alias, which is upstream. The other is a
`PytestWarning` reporting that pytest could not remove one of its own temporary directories, with
`OSError: [Errno 53]`. That is the sandbox blocking deletions under the temp tree, not a defect in the
code under test.

## 19. Defect Found and Fixed During Verification

The first full-suite run did not complete. It wedged inside
`test_reloading_one_device_leaves_the_other_untouched` and sat there for over sixteen minutes with the
process alive, which ruled out a crash and a simple hang of the whole suite. Two probes identified the
cause rather than guessing at it.

| Probe | Result |
|---|---|
| `pg_stat_database.xact_commit` sampled twice | 7123 to 7445 in twenty five seconds, so the process was running, not deadlocked at the OS level |
| `pg_stat_database` sampled again after thirty minutes | Still climbing, with both devices `MOTOR-001` and `MOTOR-002` writing telemetry at about ten rows per second |
| `py-spy dump` on the pytest process | The event loop idle in `_poll`, so a coroutine was awaiting work that would never settle |
| Task stack dump from inside the loop | The test coroutine was parked at `test_integration.py:495` awaiting a task named `gateway-MOTOR-002` whose state was `cancelling` |

A task named `cancelling` that never finishes means cancellation was requested and the coroutine never
observed it. The root cause is in `DeviceRuntime.stop`, which cancelled the poll task and then awaited
it without any bound:

```python
task.cancel()
with contextlib.suppress(asyncio.CancelledError):
    await task          # unbounded
```

Cancellation is cooperative. A runtime parked inside a protocol client read can fail to observe it, and
when that happens the awaiter is stuck permanently. Phase 6.7 called `stop` mainly during shutdown. The
Phase 6.8 controlled reload is the first code path that stops a live runtime and then needs to continue,
so it exposed the defect.

Reproduction confirmed the race rather than a deterministic failure. Five consecutive isolated runs of
the same test passed in about eleven seconds each, and the original full-suite run wedged on the same
test. An intermittent deadlock is worse than a deterministic one, because a single green run says
nothing.

The fix bounds the wait and keeps the stop finite:

```python
task.cancel()
done, _pending = await asyncio.wait({task}, timeout=STOP_TIMEOUT_SECONDS)
```

The first version of that fix was not correct, and the suite said so. It broke
`test_start_and_stop_a_device` in the connectivity API with `RuntimeError: Event loop is closed`, raised
from `f.add_done_callback` inside `asyncio.wait`. The runtime task in that test is already finished and
belongs to a request-scoped loop that has since closed, and `asyncio.wait` schedules a done callback on
the task's own loop, which raises once that loop is closed. The previous `await task` happened to tolerate
it, because an already-done task is returned without scheduling anything.

The defect was reproduced in isolation to confirm the cause rather than assume it. The same module failed
with the new code and passed with the previous implementation restored in process, which is what
established that the failure was introduced rather than pre-existing. The wait is now guarded:

```python
if task.done():
    ...retrieve the outcome, never touch the loop...
elif task.get_loop() is asyncio.get_running_loop():
    done, _pending = await asyncio.wait({task}, timeout=STOP_TIMEOUT_SECONDS)
else:
    log gateway_runtime_stop_cross_loop
```

A finished task is read for its outcome so an exception is not left unretrieved, a task owned by another
loop is not awaited from this one, and the bound still applies on the loop that owns the task. The adapter
release below the task handling is what actually frees the connection in every case.

When the deadline expires the task is abandoned, the adapter is still released, the device still reports
`STOPPED`, and the event is logged as `gateway_runtime_stop_deadline_exceeded`. The abandoned task is not
leaked indefinitely in practice, because releasing the adapter makes its next read fail, which drives it
through its own bounded retry path to termination.

The regression test `test_stop_is_bounded_when_a_read_refuses_cancellation` uses an adapter that parks
inside a read and swallows cancellation, which is the dangerous half of the real behaviour. It was run
against the old implementation in process and failed with `stop must return instead of awaiting a wedged
poll task`, then passed against the fix. That comparison was repeated after the loop guard was added, and
the test still fails against the old code, so the guard did not weaken its detection power. The test
bounds itself, so a future regression fails loudly
instead of hanging the suite.

## 20. Deviations

| Deviation | Reason | Impact |
|---|---|---|
| Publish demotes the incumbent before promoting the successor | PostgreSQL evaluates the partial unique index per statement | None; the invariant holds at every intermediate statement |
| `synchronize_session="fetch"` on the archive bulk update | Avoids a stale identity-map entry reported as published | None; correctness fix |
| Validation classifier made public and shared | The write path and `/validate` must return identical codes | None; removed a divergence |
| `DeviceRuntime.stop` gained a bounded wait on the cancelled poll task | The uncontrolled reload path deadlocked on a wedged read | Reliability improved; the gateway acquisition behaviour is unchanged |
| OPC UA simulator extended to eight nodes in the integration test | The shipped simulator exposes five signals; the canonical contract requires eight | Test-local extension only; the simulator is unchanged |

No fabricated metrics, no back-filled numbers, and no unexecuted claims appear in this report. Every
figure above was read from an executed command's output.

## 21. Open Items

| ID | Item | Status |
|---|---|---|
| O-1 | Single active coordinator assumption | Carried from Phase 6.7; deferred to a future HA or productionization phase |
| O-2 | Configuration change approval workflow | Out of Phase 6.8 scope; publishing requires no second approver in this phase |
| O-3 | RBAC on asset and configuration endpoints | Explicitly out of scope; the actor header is informational only |
| O-4 | Connectivity verification after apply | Deliberately excluded to keep validation side-effect free |
| O-5 | Parent type is not independently enforced by the database | Check constraints validate the child row only; a direct SQL insert could nest a `LINE` under a `LINE`. Closure via the API is enforced and tested. A trigger or a composite key would close it at the database level and is deferred rather than added late in this phase |

## 22. Git

Two feature commits on `main`, pushed to `origin`. No tag and no release were created.

```text
feat: add versioned device configuration management
feat: add asset configuration control tower
```

Phase 6.8 stops here. No Phase 6.9, Phase 7, RBAC, Kubernetes, or cloud infrastructure work begins
until acceptance is given.
