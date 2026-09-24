# Organization Model — Phase 6.13-B

## Purpose

Phase 6.13-B gives the platform an **enterprise governance hierarchy**: who
owns which plant, which areas a plant contains, which devices live in each
area, and which identities may act where. It builds on the Phase 6.12
identity/RBAC foundation and the Phase 6.13-A authenticated-actor migration;
it adds a second axis to authorization without replacing either.

The design goal is the same as 6.12: a small number of decisions made once,
in code, and enforced everywhere through one mechanism. That mechanism is
`app/security/scope_policy.py`, and it is the only place a scope decision is
made.

### What this phase is not

- Not a second device or asset system. A device's master record stays in
  `devices`; an asset's place in the physical tree stays in `asset_nodes`.
  The new tables describe *governance*, and `device_scopes` is a single
  association row, never a copy of device data.
- Not multi-tenancy. There is one deployment, one database, one permission
  vocabulary. Organizations partition devices, not data.
- Not attribute-based access control. Scope is a tree containment question;
  there are no rules, conditions, or expressions.

## The hierarchy

```
Organization ──< Plant ──< Area ──< DeviceScope >── devices (existing master record)
     │                                        │
     └──────────< UserScope ──────────────────┘
              (a binding names any level of the tree)
```

| Table | Owner | Notes |
|---|---|---|
| `organizations` | `app/security/org_models.py` | One row per enterprise. Unique `name`. |
| `plants` | `app/security/org_models.py` | Belongs to one organization. Unique `(organization_id, name)`. |
| `areas` | `app/security/org_models.py` | Belongs to one plant; the leaf devices attach to. Unique `(plant_id, name)`. |
| `user_scopes` | `app/security/org_models.py` | `(user_id, scope_level, scope_id)` composite PK. `scope_level` is `ORGANIZATION`, `PLANT`, or `AREA`, enforced by a check constraint. |
| `device_scopes` | `app/security/org_models.py` | `device_id` is the primary key: a device lives in **at most one** area. |

Every foreign key in the hierarchy cascades deletes downward. Removing an
organization removes its plants, their areas, the bindings naming them, and
the device associations beneath them. Scope is structure, so removing the
structure removes the reach, and that is observable: a bound operator whose
plant was deleted is refused with `403 SCOPE_DENIED` on the next request, and
the refusal is audited.

`user_scopes.scope_id` deliberately carries no foreign key: it names a row in
one of three tables depending on `scope_level`, SQL has no polymorphic foreign
key, and the scope API validates the pair before inserting. The check
constraint on `scope_level` is the database's say in the matter; the
existence check is the API's.

## Scope evaluation

One function answers every reach question:
`app/security.scope_policy.resolve_device_scope(session, principal)`.

| Caller shape | Answer |
|---|---|
| Holds `*` (ADMIN) | `None` — unrestricted, always. A binding cannot shrink ADMIN |
| No bindings | `None` — unrestricted, by the documented migration default |
| Bound to subtrees | The device ids associated with the areas inside those subtrees |
| Bound, no devices assigned | The empty set — a real answer that denies |

The migration default is stated in code and in `docs/SECURITY_MODEL.md`:
every operator created before 6.13-B has no bindings, and flipping the default
to deny would lock a working plant on upgrade. When the deployment is ready,
the default is a one-line change in `scope_policy.py` plus a test update —
which is exactly why all scope decisions live in one module.

Three public functions cover every use:

| Function | Used for |
|---|---|
| `resolve_device_scope` | the raw answer, for tests and list filters |
| `ensure_device_in_scope` | single-device mutation/read guard: audits `scope.denied` then raises `403 SCOPE_DENIED` |
| `device_scope_filter` | list endpoints: `None` means no filter, a set means membership |

Enforcement points in this phase: alarm acknowledge / clear / detail /
related, the alarm list filter, every device-configuration route, connectivity
detail / start / stop, and asset attach / detach.

## API

All routes are mounted under both `/api/v1` and `/api` and appear in the
`docs/SECURITY_MODEL.md` enforcement matrix.

| Surface | Permission | Notes |
|---|---|---|
| `GET /organizations`, `/organizations/{id}`, `/organizations/{id}/plants`, `/plants/{id}/areas` | `org.read` | Every role: the structure is visible to anyone who can act |
| `POST/PATCH/DELETE` on the same paths | `org.manage` | ADMIN only by default |
| `GET/PUT /users/{id}/scopes` | `scope.manage` | The PUT replaces the binding set wholesale, which makes it idempotent and auditable as one fact |
| `GET/PUT /devices/{device_id}/scope` | `scope.manage` | Body is `{"area_id": ... | null}`; `null` clears the assignment |

`org.read`, `org.manage`, and `scope.manage` are the Phase 6.13-B additions to
the permission vocabulary. `scope.manage` is granted to ADMIN only: a boundary
an operator can redraw is not an organizational boundary.

## Audit

Every mutation on this surface writes one `audit_events` row through the same
writer the business surface uses, so `actor` and `actor_user_id` carry the
authenticated caller:

| Action | On |
|---|---|
| `ORGANIZATION_CREATED` / `_UPDATED` / `_DELETED` | structure authoring |
| `PLANT_CREATED` / `_UPDATED` / `_DELETED` | structure authoring |
| `AREA_CREATED` / `_UPDATED` / `_DELETED` | structure authoring |
| `USER_SCOPE_ASSIGNED` | a binding set replaced, with the new bindings in `details` |
| `DEVICE_SCOPE_ASSIGNED` | a device associated or cleared |
| `SCOPE_DENIED` (`status=DENIED`) | a refused out-of-scope attempt, written before the 403 is raised |

## Migration

`20260924_11_phase6_13_b_org_scope` creates the five tables and seeds
`org.read` to OPERATOR and VIEWER, `org.manage` and `scope.manage` to ADMIN.
It alters no existing table, and `downgrade` drops exactly what it added, in
reverse dependency order. The vocabulary parity test compares the combined
seed of all three security migrations (6.12, 6.13-A, 6.13-B) against the code
table, and asserts each migration's slice is disjoint: a later seed may only
add names.

## Non-goals

- No frontend UI for the hierarchy; the API is the deliverable of this phase.
- No per-device or per-area permission overrides; scope is containment only.
- No scope on telemetry/devices/platform routes; they are outside the governed
  surface entirely (see `docs/SECURITY_MODEL.md`).
- No asset-read filtering by scope; attaching or detaching a device checks it,
  reading the tree does not. A later phase can thread the filter through the
  asset projection.

## Verification

| Claim | Where it is checked |
|---|---|
| Hierarchy CRUD, cascade, duplicate names | `tests/security/test_scope_governance.py` |
| Binding validation, wholesale replacement, `scope.manage` gating | `tests/security/test_scope_governance.py` |
| In-scope allowed, out-of-scope refused and audited, list filtered | `tests/security/test_scope_governance.py` |
| Unbound operator and bound ADMIN keep global reach | `tests/security/test_scope_governance.py` |
| Every organization route declares its permission | `tests/security/test_route_coverage.py` |
| Combined seed equals the code vocabulary | `tests/security/test_rbac_vocabulary.py` |
