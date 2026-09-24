# Security Model — Phase 6.12

## Purpose

Phase 6.12 gives the platform an **identity and authorization foundation**: who
is calling, what that identity is allowed to do, and what was done in its name.

Before this phase the platform answered questions about equipment, incidents,
and decisions, and it could not answer the prior question. Operator actions were
attributed with an `X-Actor` header, which is descriptive metadata rather than
authentication: any client could write any name into it. This phase introduces a
real credential, a real authorization decision on the server, and an audit trail
that records the authenticated principal.

The design goal is a **coherent foundation**, not a complete security product. A
small number of decisions are made once, in code, and enforced everywhere
through one mechanism, so that a later phase can extend the model without
rewriting it.

### What this phase is not

Stated plainly, because the absence of these is a deliberate scope boundary
rather than an oversight:

- No SSO, no OAuth 2.0, no OIDC, no SAML.
- No enterprise IAM integration, no directory sync, no SCIM.
- No Zero Trust architecture: there is no device posture, no continuous
  verification, no per-request risk score.
- No MFA, no WebAuthn, no step-up authentication.
- No refresh tokens, no token revocation list, no session store.
- No Kubernetes or cloud IAM integration, no secret manager integration.
- No network policy, no mTLS, no service mesh.

## Identity

An identity is a row in `users`, owned by `app/security/models.py`.

| Field | Notes |
|---|---|
| `id` | UUID primary key |
| `username` | Unique. Normalised by `strip().casefold()`, so `Operator.One` and `operator.one` are one identity |
| `email` | Optional, unique when present, also case-folded |
| `password_hash` | A password hash, never a password |
| `status` | `ACTIVE` or `DISABLED`, enforced by a check constraint |
| `created_at` / `updated_at` | Timestamps |

### Password storage

Hashing uses **bcrypt** (`app/security/passwords.py`). The shipped cost factor
is 12; tests use 4 so the suite stays fast, and a test asserts the shipped value
so the two cannot drift into a slow production setting unnoticed. MD5, SHA-1,
and plaintext storage are not merely unused: they are absent from the module.

The password policy is deliberately narrow and stated as constants:

- at least 12 characters,
- at most 72 bytes (bcrypt truncates beyond this, so a longer password would
  silently mean something other than what the operator typed),
- not equal to the username.

The policy is not a strength meter, and it is not configurable at runtime. A
policy an operator can weaken is a policy that will be weakened.

### Verification is time-equalised

`authenticate()` verifies against a dummy hash when the username does not exist.
Without that step, "no such user" returns measurably faster than "wrong
password", and response time becomes a user-enumeration oracle.

The response for an unknown user is also byte-identical to the response for a
wrong password (`401 INVALID_CREDENTIALS`). The two failure modes are
indistinguishable to the caller and are distinguished only in the audit row,
which records the reason.

## Authorization: user → role → permission → action

```
       (data, in PostgreSQL)
  User ──< user_roles >── Role ──< role_permissions >── Permission
                                                              │
                                            (code, in rbac.py)
                                                              ▼
                                              require_permission("incident.ack")
                                                              │
                                                              ▼
                                                     protected route
```

Two halves of the model are stored differently, and the split is the point.

**The vocabulary is code.** A permission is a `resource.action` string declared
as a constant in `app/security/rbac.py`. A route references it by name. Adding a
permission requires editing that module, so a permission cannot come into
existence by accident in a migration or a spreadsheet.

**The mapping is data.** Roles, permissions, and grants live in
`roles`, `permissions`, `user_roles`, and `role_permissions`. At request time,
authorization reads those rows. Revoking a grant takes effect on the **next
request**, not the next deployment, and never by editing a token.

`ROLE_PERMISSIONS` in `rbac.py` is the *seed*, not the runtime truth. A test
asserts the seeded rows equal that table, so drift between the migration and the
code is caught instead of tolerated.

### Default roles

| Role | Grants | Intent |
|---|---|---|
| `ADMIN` | `*`, `user.manage` | Unrestricted authority, including identity and role management |
| `OPERATOR` | `telemetry.read`, `dashboard.read`, `incident.read`, `incident.create`, `incident.ack`, `incident.investigate`, `incident.resolve`, `incident.close`, `incident.reopen`, `workflow.read`, `workflow.start`, `workflow.cancel`, `approval.read`, `approval.review`, `workorder.read` | Runs the incident, workflow, and approval loop for a plant |
| `VIEWER` | `telemetry.read`, `dashboard.read`, `incident.read`, `workflow.read`, `approval.read`, `workorder.read` | Read-only observer |

`*` is reserved for `ADMIN`. It is an **exact-match** grant, checked as
`permission in permissions`, not an `fnmatch` pattern. A permission that
happened to be named `incident.*` therefore cannot be mistaken for wildcard
authority, and `Principal.has_permission` in the backend and
`permissionGranted` in the frontend implement the identical rule.

`VIEWER` is deliberately a superset of nothing and a subset of `OPERATOR`. A
test asserts `OPERATOR ⊇ VIEWER` so the read-only role can never quietly lose a
read it needs, and a test asserts `VIEWER` holds no write permission.

### The enforcement matrix

Every route below declares its permission through
`require_permission(...)`. A test walks the live route table and compares it to
this matrix, so a route added without a permission fails the build.

| Method | Path | Permission |
|---|---|---|
| POST | `/api/v1/incidents` | `incident.create` |
| GET | `/api/v1/incidents` | `incident.read` |
| GET | `/api/v1/incidents/{id}` | `incident.read` |
| GET | `/api/v1/incidents/dashboard` | `incident.read` |
| GET | `/api/v1/incidents/metrics` | `incident.read` |
| GET | `/api/v1/incidents/{id}/context` | `incident.read` |
| GET | `/api/v1/incidents/{id}/workflow-context` | `incident.read` |
| POST | `/api/v1/incidents/{id}/acknowledge` | `incident.ack` |
| POST | `/api/v1/incidents/{id}/investigate` | `incident.investigate` |
| POST | `/api/v1/incidents/{id}/resolve` | `incident.resolve` |
| POST | `/api/v1/incidents/{id}/close` | `incident.close` |
| POST | `/api/v1/incidents/{id}/reopen` | `incident.reopen` |
| POST | `/api/v1/incidents/{id}/start-workflow` | `workflow.start` |
| POST | `/api/v1/incidents/{id}/workflows` | `workflow.start` |
| GET | `/api/v1/workflow-metrics` | `workflow.read` |
| GET | `/api/v1/workflows`, `/api/v1/workflows/{id}`, `/api/v1/workflows/{id}/trace` | `workflow.read` |
| POST | `/api/v1/workflows/{id}/cancel` | `workflow.cancel` |
| GET | `/api/v1/approvals/pending`, `/api/v1/approvals/{id}` | `approval.read` |
| POST | `/api/v1/approvals/{id}/approve`, `/api/v1/approvals/{id}/reject` | `approval.review` |
| GET | `/api/v1/work-orders`, `/api/v1/work-orders/{id}` | `workorder.read` |

The legacy `/api` prefix mirrors `/api/v1` and enforces exactly the same
permissions; a test asserts that every mirror declares what its `/api/v1`
counterpart declares, so the second prefix cannot become a softer entrance.

`approval.review` is new in this phase. It separates **reading** a decision from
**making** one, which the platform previously conflated. The approval state
machine itself is untouched: the same transitions, the same
`WAITING_APPROVAL` gate, the same audit of the decided plan. Only the question
"may this caller decide?" is answered by a permission instead of by presence.

## Security boundary

Two failure modes are kept strictly distinct, because collapsing them produces a
worse interface and a worse audit trail:

| Condition | Status | Code |
|---|---|---|
| No usable identity was presented | `401` | `AUTHENTICATION_REQUIRED`, `INVALID_TOKEN`, `TOKEN_EXPIRED`, `INVALID_CREDENTIALS`, `ACCOUNT_DISABLED` |
| An identity was presented and is not permitted | `403` | `PERMISSION_DENIED` with `details.required_permission` |
| Too many failed sign-ins from one origin | `429` | `LOGIN_RATE_LIMITED` with `details.retry_after_seconds` |
| No signing secret is configured | `503` | `SECURITY_NOT_CONFIGURED` |

`403` responses name the missing permission in their details. That is
intentional and safe: it tells an authenticated operator what authority they
lack, and it tells an unauthenticated caller nothing, because they never get a
`403`.

### Tokens

Access tokens are **HS256 JWTs** (`app/security/tokens.py`) with required claims
`sub`, `user_id`, `roles`, `iat`, and `exp`. Verification rejects, explicitly
and separately: an unsigned (`alg: none`) token, a token signed with the wrong
secret, a structurally malformed token, a token missing a required claim, a
token whose `typ` is not `access`, a subject that is not a UUID, and an expired
token. Expiry is checked against an injectable clock so the boundary is tested
exactly rather than approximately.

The token carries `roles`, but **authorization never reads them**. Roles are in
the token so the audit trail can record what the caller claimed at issue time;
permissions are recomputed from the database on every request. This is what
makes revocation immediate.

### Login rate limiting

`POST /auth/login` counts failures per source address in Redis and answers `429`
once the budget is spent (default: 5 failures per 60 seconds). The source address
is the socket peer. `X-Forwarded-For` is **not** trusted: it is client-supplied,
and trusting it without a configured proxy boundary would let an attacker choose
their own bucket or forge the address written to the audit trail.

The limiter **fails open** when Redis is unreachable, and logs that it did. This
is a deliberate trade: the alternative is locking every operator out of a working
platform because a cache is down. It is recorded here as a known limitation
rather than hidden.

## Audit

`audit_events` gained four columns in this phase: `actor_user_id`, `ip_address`,
`user_agent`, and `resource_id`. The columns are nullable, so pre-existing rows
and pre-existing writers keep working unchanged.

Security events use a single shape:

```json
{
  "actor": "operator.one",
  "action": "incident.acknowledge",
  "resource": "incident",
  "resource_id": "3f2b…",
  "status": "SUCCESS"
}
```

| Event | Recorded on |
|---|---|
| Sign-in succeeded | `action=login`, `status=SUCCESS`, with the acting identity |
| Sign-in failed | `action=login`, `status=FAILURE`, with the reason and **no** user id |
| Registration | `action=register`, with whether a requested role was ignored |
| Permission denied | `action=permission.denied`, `status=DENIED`, with the required permission, method, and path |
| Incident acknowledged / resolved | the lifecycle transition, with the authenticated actor |
| Workflow started | the delegation to the engine |
| Approval decided | the human decision |

Two audit conventions coexist and are documented in
`app/repositories/audit.py`: the legacy convention puts an identifier in
`resource` (for example `resource="MOTOR-001"`), while security events put the
**resource type** in `resource` and the **instance** in `resource_id`. The
security convention is the one to use going forward; the legacy rows are left
as they are rather than rewritten.

The acting identity reaches the audit layer through a request-scoped
`SecurityContext` published by the authentication dependency into a
`ContextVar` and cleared at the start of every request by the correlation
middleware. A writer therefore does not have to thread the principal through
every call signature, and no identity can leak from one request into the next.

## Secret governance

`scripts/security_scan.py` scans every version-controlled file with a scannable
suffix for credential-shaped assignments: `*_API_KEY`, `*_PASSWORD`, `*_TOKEN`,
`*_SECRET`, and credentials embedded in a URL.

It reports a finding only when a value **looks like a credential**, which means
it clears a Shannon-entropy floor (3.0 bits per character) and a minimum length
(16 characters, or 8 for a URL password), and does not carry a snake_case
identifier shape. An explicit allow-list of placeholders (`change-me`,
`${VAR}`, `<...>`) passes. This is what separates a real secret from
`POSTGRES_PASSWORD=change-me-in-dotenv`.

It is wired into CI in the `deployment` job and exits non-zero on any finding.
Tests cover both directions: a realistic secret is reported, and every
placeholder actually used in this repository passes.

`scripts/create_admin.py` bootstraps the first administrator. It reads the
password from `SECURITY_BOOTSTRAP_PASSWORD` or prompts with echo disabled, never
from `argv`, because a password in a command line lands in shell history and in
the process table. It is idempotent and warns on a weak password, but does not
refuse: bootstrapping an administrator who cannot sign in would be a worse
outcome than a weak one that is logged.

## Operator interface

The interface never holds authority. It holds a **view** of what the server said
this identity may do, so that it can avoid offering an action that would only be
refused.

- The access token lives in `sessionStorage`, behind a `TokenStorage` interface
  (`src/authStorage.ts`). Session scope, not persistent: an operator token that
  survives a browser restart survives on a shared plant terminal too. Blocked or
  private-mode storage degrades to an in-memory store, so sign-in still works.
- `AuthProvider` (`src/auth.tsx`) has three states: `anonymous`, `restoring`
  (a token survived a reload and `/auth/me` is in flight), and `authenticated`.
  The shell is not painted during `restoring`, because a shell painted before
  the identity is known would flash actions the operator may not have.
- Permissions are taken from `GET /auth/me`, never from the token or from the
  sign-in response. A rejected `401` anywhere clears the token and collapses the
  session in one place; a `403` does not, because it means the identity is fine
  and the permission is missing.
- `RequireAuth` is a route guard. An anonymous visitor reaches only the sign-in
  page, and the attempted location is preserved so sign-in returns them to where
  they were going.
- Actions the caller cannot perform are **not rendered**: a `VIEWER` sees a
  readable incident with no lifecycle buttons and a line explaining that their
  role may read but not act, and an identity without `approval.review` sees the
  plan and the evidence but no decision form.

The hiding is a courtesy. Every hidden action is enforced on the route itself,
and a test asserts that a server refusal still surfaces as an error when the
action was offered anyway.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SECURITY_JWT_SECRET` | *(empty)* | Token signing secret. Empty fails closed: the API refuses to mint or accept tokens (`503`) rather than trusting unsigned ones |
| `SECURITY_ACCESS_TOKEN_TTL_SECONDS` | `3600` | Access-token lifetime. Tokens are not revocable, so this bounds how long a leaked token is useful |
| `SECURITY_REGISTRATION_ENABLED` | `true` | Self-service registration. A self-registered identity always receives `VIEWER` |
| `SECURITY_LOGIN_RATE_LIMIT_ATTEMPTS` | `5` | Failed sign-ins per source address per window |
| `SECURITY_LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `60` | Length of that window |

`SECURITY_JWT_SECRET` is empty in `.env.example` by design. Generate a real value
with `openssl rand -hex 32` and inject it from the operator's secret store.

## Non-goals and known limitations

These are honest statements of where the foundation stops. Each is a candidate
for a later phase, not a defect being hidden.

1. **The legacy `X-Actor` header is still in use outside the governed surface.**
   Alarms, alarm rules, assets, device configuration, connectivity, and
   observability routes are not covered by RBAC in this phase, and
   `app/api/dependencies.py` records that boundary in the source. Until those
   routes are migrated, treat the audit actor on those paths as descriptive
   rather than authenticated.
2. **Tokens cannot be revoked.** Disabling an identity takes effect on the next
   request, because the user row is loaded per request. A password change is not
   implemented, and implementing one would not invalidate outstanding tokens.
   The TTL is the only bound.
3. **The rate limiter fails open** when Redis is unavailable, and it protects one
   endpoint. A general rate-limiting gateway belongs at an edge proxy, and
   pretending otherwise in the application would produce a limiter that a second
   instance trivially bypasses.
4. **No MFA, no password rotation, no account lockout** beyond the rate limit.
5. **Permissions are coarse and role-based.** There is no attribute-based
   policy, no per-asset or per-plant scoping, and no separation of duties within
   a role.
6. **There is no role-management API.** Roles and grants are seeded by migration
   and changed in SQL. The data model supports a management surface; this phase
   does not ship one.
7. **The frontend bundle, HTTP transport, and database connections are not
   further hardened** here: no CSP, no HSTS, no mTLS, no TLS configuration.

## Verification

| Claim | Where it is checked |
|---|---|
| Password hashing, cost factor, policy | `tests/security/test_password_and_tokens.py` |
| Token signing, expiry, tampering, `alg: none` | `tests/security/test_password_and_tokens.py` |
| Registration, sign-in, disabled identity, `/me` | `tests/security/test_authentication.py` |
| `401` vs `403`, role limits, live revocation | `tests/security/test_rbac_enforcement.py` |
| Audit rows for sign-in, denial, lifecycle | `tests/security/test_audit_security.py` |
| Rate limiting and its fail-open behaviour | `tests/security/test_rate_limit.py` |
| Seeded grants equal the code table | `tests/security/test_rbac_vocabulary.py` |
| Every governed route declares its permission | `tests/security/test_route_coverage.py` |
| The scanner reports real secrets and passes placeholders | `tests/security/test_security_scan.py` |
| Token storage, guard, hidden actions, server re-verification | `frontend/src/security.test.tsx` |
