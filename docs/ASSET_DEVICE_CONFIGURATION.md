# Asset and Device Configuration Management

Phase 6.8 adds a minimal asset hierarchy and versioned, immutable device configuration management on
top of the Phase 6.7 Industrial Protocol Gateway. It answers three operational questions that the
gateway alone could not answer:

1. Where is this device physically located in the plant?
2. Which acquisition configuration should be running, and which one actually is?
3. What changed, when, by whom, and did the change take effect?

The scope is deliberately narrow. This is a configuration control surface, not a CMDB, not SCADA,
and not a write path to any industrial device.

## Scope Boundary

| In scope | Out of scope |
|---|---|
| SITE → LINE location hierarchy over existing devices | Deep asset taxonomy, spare parts, maintenance history |
| Versioned immutable acquisition configuration per device | Real-time control, setpoint writes, actuation |
| Desired versus applied version with honest drift reporting | Connectivity probing from the validation path |
| Controlled reload of a single device runtime | Fleet-wide hot reload or rolling deployment orchestration |
| Audit of configuration lifecycle events | Role-based access control, multi-tenant ownership |

Device identity is unchanged. `devices.device_id` remains the single identity source. No second
device table and no parallel identity system is introduced, because two identity sources would make
"which device is this" ambiguous at exactly the moment a misconfiguration matters.

## Data Model

Three tables are added, and one nullable column is added to the existing `devices` table.

### `asset_nodes`

Minimal location tree. `SITE` nodes are roots; `LINE` nodes require a `SITE` parent.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `name` | VARCHAR(200) | Display name |
| `asset_type` | VARCHAR(20) | `SITE` or `LINE` |
| `parent_id` | UUID | FK to `asset_nodes.id`, `ON DELETE RESTRICT` |
| `description` | TEXT | Free text |
| `metadata` | JSONB | Extension bag |
| `created_at` / `updated_at` | TIMESTAMPTZ | Server maintained |

Two check constraints enforce the shape rather than trusting the application layer:

- `ck_asset_nodes_type` restricts `asset_type` to the two supported levels.
- `ck_asset_nodes_parent_shape` requires `SITE` to have no parent and `LINE` to have one.

The parent FK uses `ON DELETE RESTRICT`, so a parent that still has children cannot be removed. A
node that still has an attached device cannot be removed either, enforced in the service layer and
backed by the FK from `devices`. There is no code path that produces an orphaned child.

Cycle prevention is enforced at the service layer, which is the only path the product exposes.
`ASSET_PARENT_RULES` declares that `SITE` accepts no parent and `LINE` requires a `SITE` parent, and
the service resolves the named parent and rejects the request when its `asset_type` does not match.
A cycle would require a `LINE` parented by a `LINE`, which that rule refuses, so no API call can
produce one.

The database enforces the shape of each row independently, which is a narrower guarantee than the
full type rule. A direct SQL insert could still create a `LINE` whose parent is another `LINE`,
because the check constraint validates the child's own fields and cannot read the parent row. This
is recorded as an open item rather than described as a database guarantee.

Depth is capped by the same service rule. There is no third level, so a request that would nest a
`LINE` under a `LINE` is refused with a structured hierarchy error.

### `devices.asset_node_id`

Nullable FK to `asset_nodes.id` with `ON DELETE RESTRICT`, indexed as `ix_devices_asset_node_id`. A
device with `NULL` here is unassigned and appears in a dedicated section of the UI rather than being
silently hidden.

### `device_configurations`

Immutable version snapshots. The payload column is the existing Phase 6.7 `DeviceDefinition` model,
stored as JSONB.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `device_id` | VARCHAR | FK to `devices.device_id`, `ON DELETE RESTRICT` |
| `version` | INTEGER | Monotonic per device, `> 0` |
| `status` | VARCHAR(20) | `DRAFT` / `VALIDATED` / `PUBLISHED` / `ARCHIVED` |
| `protocol` | VARCHAR(20) | Denormalized for list rendering |
| `configuration` | JSONB | Full typed definition snapshot |
| `created_by` | VARCHAR(200) | Actor, defaults to `system` |
| `validated_at` / `published_at` / `archived_at` | TIMESTAMPTZ | Lifecycle timestamps |
| `validation_result` | JSONB | Structured outcome of the last validation |
| `validation_error` | TEXT | Flattened message when validation failed |

Constraints of note:

- `uq_device_configurations_device_version` makes `(device_id, version)` unique.
- `ck_device_configurations_published_at` ties `published_at IS NOT NULL` to the published or
  archived states, so a row can never claim publication without a timestamp.
- `uq_device_configurations_single_published` is a partial unique index on `device_id WHERE status =
  'PUBLISHED'`. PostgreSQL evaluates a unique index on every statement, not only at commit, so the
  service demotes the incumbent published row before promoting its successor inside the same
  transaction. This ordering is load-bearing, and the reason is recorded in the code and in the
  service tests.

### `device_configuration_runtime_status`

Observed runtime state, deliberately separated from the immutable snapshots.

| Column | Type | Notes |
|---|---|---|
| `device_id` | VARCHAR | Primary key, FK `ON DELETE CASCADE` |
| `desired_version` | INTEGER | Published version the device should run |
| `applied_version` | INTEGER | Version the gateway actually started |
| `apply_status` | VARCHAR(20) | `PENDING` / `APPLYING` / `APPLIED` / `FAILED` |
| `source` | VARCHAR(20) | `database` / `bootstrap` / `none` |
| `last_apply_at` | TIMESTAMPTZ | When the last attempt ran |
| `last_apply_error` | TEXT | Failure cause when `apply_status = FAILED` |

Separating this table is a correctness decision. A snapshot that mutates after publication stops
being evidence. Desired and applied versions describe the present; the snapshot describes what was
approved.

## Configuration Lifecycle

```text
DRAFT ──validate──▶ VALIDATED ──publish──▶ PUBLISHED ──supersede──▶ ARCHIVED
  ▲                                            │
  └──────────── clone ─────────────────────────┘
```

| State | Mutable | Meaning |
|---|---|---|
| `DRAFT` | Yes | Work in progress. Never applied. |
| `VALIDATED` | No | Passed the typed validator. Still not applied. |
| `PUBLISHED` | No | The desired version for this device. Exactly one per device. |
| `ARCHIVED` | No | A former published version retained for history and rollback. |

A published snapshot is never edited in place. Changing a live device follows clone, edit, validate,
publish. Rollback republishes an older archived snapshot as a new version, so the action itself is
auditable and the previous state is never destroyed.

Validation is side-effect free. It parses the payload through the same typed validator the gateway
consumes and returns structured issues of the form `{field, code, message}`. It performs no
connectivity probe, opens no socket, and writes nothing. The write path and the explicit `/validate`
endpoint share one classifier, so the same payload produces identical codes in both.

## Source of Truth

The database is the source of truth for the desired configuration. Startup resolution order for a
managed device is:

1. The single `PUBLISHED` configuration row for that device.
2. A bootstrap definition, when no published row exists.

The restart-recovery test runs with managed resolution enabled and no YAML definition file present,
which proves the runtime rebuilds from the database rather than from a local document. A device whose
resolution source is `bootstrap` reports `source = bootstrap`, so an operator can tell the two apart.

## Desired versus Applied

Publication and application are separate steps, and the system reports them separately.

| Field | Meaning |
|---|---|
| `desired_version` | Published version, from `device_configurations` |
| `applied_version` | Version the running gateway actually started |
| `apply_status` | Outcome of the most recent apply attempt |
| `in_sync` | True only when applied equals desired and the last attempt succeeded |

Two properties follow from this design.

A failed application never destroys a healthy runtime. The apply path validates and prepares the new
definition before touching the running one, so a bad version leaves the previous runtime polling.
The integration test `test_a_bad_version_cannot_take_a_healthy_runtime_down` asserts that the healthy
device keeps producing telemetry after the failed attempt.

A failed application is reported as drift, never as success. When the applier raises, the exception
is caught, converted into an `ApplyOutcome` with `success=False`, and recorded with
`apply_status = FAILED` and a populated `last_apply_error`. The request returns a normal response
describing drift; it does not surface as a 500, and it does not claim the version took effect.

`APPLYING` is committed before the runtime is touched. A crash in the middle of an apply therefore
leaves an honest transient state rather than a stale `APPLIED`. An unavailable applier reports `503`
rather than returning a fabricated success.

## Runtime Reload

Reload is scoped to one device. Applying a configuration stops and rebuilds only the target device's
runtime; every other runtime keeps its existing poll loop and connection. The integration test
`test_reloading_one_device_leaves_the_other_untouched` asserts that a second device's telemetry
continues uninterrupted across another device's reload.

Failure is isolated in the same way. A definition that cannot be constructed affects only its own
device, because construction happens before the live runtime is replaced.

## Validation Rules

The validator enforces the canonical eight-signal contract and refuses the shortcuts that would make
a configuration look complete while behaving differently at runtime.

| Rule | Behavior |
|---|---|
| Typed shape | Payload must parse as `DeviceDefinition`; failures return `FIELD_INVALID` with the field path |
| Protocol support | Only `MQTT`, `OPC_UA`, `MODBUS_TCP`, `SIMULATOR` are accepted |
| Signal coverage | Every canonical signal must be mapped; missing ones return `MISSING_SIGNAL` naming each |
| No synthetic fill | A signal without a real source is a validation error, never a zero-filled default |
| No plaintext secrets | Credential fields accept an opaque `secret_ref` or `credential_ref` only |
| No I/O | Validation opens no socket and performs no connectivity probe |

## API Surface

All routes are exposed under both `/api/v1` and `/api`, matching the existing dual-prefix
convention. Both prefixes are covered by the API tests.

### Assets

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/assets` | Flat list of asset nodes with direct device counts |
| `GET` | `/assets/tree` | Full hierarchy plus unassigned devices |
| `POST` | `/assets` | Create a `SITE` or `LINE` |
| `GET` | `/assets/{asset_id}` | Read one node |
| `DELETE` | `/assets/{asset_id}` | Delete a node, refused while it has children or devices |
| `PUT` | `/assets/{asset_id}/devices/{device_id}` | Attach a device to a line |
| `DELETE` | `/assets/{asset_id}/devices/{device_id}` | Detach a device |

### Device Configurations

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/devices/{device_id}/configurations` | Version history, newest first |
| `POST` | `/devices/{device_id}/configurations` | Create a draft |
| `GET` | `/devices/{device_id}/configurations/{version}` | Read one version with its snapshot |
| `PATCH` | `/devices/{device_id}/configurations/{version}` | Edit a draft |
| `DELETE` | `/devices/{device_id}/configurations/{version}` | Delete a draft |
| `POST` | `/devices/{device_id}/configurations/{version}/validate` | Validate without persisting changes |
| `POST` | `/devices/{device_id}/configurations/{version}/clone` | Clone into a new draft |
| `POST` | `/devices/{device_id}/configurations/{version}/publish` | Publish, demoting the incumbent |
| `GET` | `/devices/{device_id}/configuration/status` | Desired versus applied state |
| `POST` | `/devices/{device_id}/configuration/apply` | Retry application of the published version |
| `GET` | `/devices/{device_id}/configuration/audit` | Lifecycle audit, newest first |

### Status Semantics

| Code | Condition |
|---|---|
| `404` | Unknown device, unknown version, unknown asset node |
| `409` | Editing or publishing a non-draft, conflicting lifecycle transition, occupied parent |
| `422` | Payload fails typed validation, with `details.errors` carrying structured issues |
| `503` | Configuration applier unavailable |

An optional actor header identifies the operator in audit records. When it is absent or invalid the
actor defaults to the system identity; there is no authentication and no RBAC in this phase.

## Audit

Lifecycle events are recorded in the existing `audit_events` table rather than a new one, so
configuration history is queryable alongside the platform's other audit records. Recorded events
cover creation, update, validation, publication, clone, deletion, apply attempts, and apply failures.

Audit records carry the device, event type, configuration version, actor, status, timestamp, and a
short summary. They never carry secrets, and no credential value enters the audit table.

## Frontend

The `/assets-config` route renders the hierarchy and the configuration panel.

- Unity view of the tree with devices under their line, and an explicit unassigned section
- Per-device protocol, published version, applied version, and apply status
- A drift banner whenever applied differs from desired, or the last apply failed
- Draft editor over the raw JSON snapshot, with validate, publish, clone, and delete
- Version history with lifecycle timestamps
- Audit trail, newest first
- Attach and detach controls for moving a device between lines

Status is never presented as color alone. The UI states that device identity comes from the existing
registry and that publishing a configuration changes acquisition settings only, not control of the
equipment.

## Security Boundary

| Property | Guarantee |
|---|---|
| Device identity | Unchanged; `devices.device_id` is the only identity source |
| Control path | None; no PLC, Modbus, or OPC UA write and no actuation exists |
| Secrets | Opaque references only; plaintext credentials are rejected by the validator |
| Audit | No secret value is written to `audit_events` |
| Validation | Side-effect free; no probe, no socket, no write |
| Published rows | Immutable; changes require a new version |

## Relationship to the Gateway

Phase 6.7 introduced declarative device onboarding from a definition document. Phase 6.8 replaces the
document with a versioned database record as the desired state, while reusing the same
`DeviceDefinition` model, the same gateway, the same adapters, and the same canonical eight-signal
contract. The gateway is not modified in its acquisition behavior; it gains a database-backed
resolution source and a controlled reload entry point.

## Tests

| Suite | Coverage |
|---|---|
| `tests/assetconfig/test_assets.py` | Hierarchy rules, parent constraints, delete refusal, attach/detach |
| `tests/assetconfig/test_validation.py` | Typed validation, signal coverage, secret rejection, side-effect freedom |
| `tests/assetconfig/test_configuration.py` | Lifecycle, immutability, single published, apply states, raise-safe apply |
| `tests/assetconfig/test_api.py` | Full HTTP surface, status codes, dual prefixes, audit ordering |
| `tests/assetconfig/test_integration.py` | Published config → gateway → simulator → PostgreSQL telemetry |
| `frontend/src/assetsconfig.test.tsx` | Hierarchy rendering, drift honesty, editor workflow, refusal states |
