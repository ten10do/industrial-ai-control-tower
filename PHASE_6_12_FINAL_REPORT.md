# Phase 6.12 Final Report — Security & Governance Foundation

**Status**: PHASE_6_12_BLOCKED — `REMOTE_PUSH_WITHHELD` (see section 0)
**Base commit**: `2379224` (Phase 6.11) · **Branch**: main · **Phase commit**: `21bb321`
**Constraint compliance**: no business-flow, Agent, Workflow Graph, Approval
state-machine, WorkOrder, ML, or RAG changes; no Cloud, Kubernetes, SSO,
Enterprise IAM, OAuth, or Zero Trust work; no tag, no release; stopped before
Phase 6.13.

## 0. Blocker — remote state divergence (read first)

Every implementation task and every local gate of this phase is complete and
green. The phase is not marked `PHASE_6_12_COMPLETE` because the final gate,
"push and confirm CI", cannot be completed honestly from the state the
repository is in. Two facts, both verified this session:

**1. Five commits from earlier phases have never been pushed.**

| Ref | Commit | Phase |
|---|---|---|
| local `main` | `21bb321` | 6.12 (this phase) |
| | `2379224` | 6.11 |
| | `4a41c18` | 6.10 |
| | `c5d852f` | 6.9-C |
| | `e5f58e7` | 6.9-B |
| | `112d879` | 6.9-A |
| `origin/main` | `2c2f216` | 6.8 (last pushed) |

The remote is a strict ancestor of local `main` (`git merge-base --is-ancestor`
succeeds), so the branch is not stale and the push would be a fast-forward with
no rewriting. The consequence is that the CI gate for Phases 6.9-A through 6.11
has never been confirmed on the remote, and pushing this phase publishes all six
commits at once. That is a governance decision about other phases' history, so
it was not taken unilaterally.

**2. `mypy` is not clean at the base commit, and CI would very likely say so.**

A fresh-cache `mypy app tests` run on an isolated worktree at `2379224` (the
unmodified Phase 6.11 base) reports **20 errors in 4 files**. The identical 20
errors appear after this phase. All four files belong to earlier phases:

```
tests/test_deployment_foundation.py          type-arg, no-untyped-def, arg-type,
                                             union-attr, index, unused-ignore
tests/incidents/test_deployment_roundtrip.py import-untyped, truthy-function
tests/incidents/test_platform_reliability.py unused-ignore (x3)
tests/test_platform_reliability.py           misc
```

`backend/requirements-dev.txt` pins `mypy>=1.10.0` without an upper bound, and
the local resolution is mypy 2.3.1, so CI installs the same generation. The
`backend` job runs `mypy app tests`, so pushing would most likely produce a red
`backend` job for reasons that pre-date this phase.

For the record, `PHASE_6_10_FINAL_REPORT.md` and `PHASE_6_11_FINAL_REPORT.md`
both claim `mypy` clean. That claim is not reproducible today against the tree
they describe. The most likely explanation is a mypy/typeshed version change
(the failing codes are version-sensitive: `index` on `object`, `unused-ignore`,
`type-arg`), not a false claim at the time. Either way, the debt is real now and
belongs to 6.10/6.11 test files, not to 6.12.

**What is needed to close the phase.** A decision, then one of:

- push as-is and record the CI outcome, including a red `backend` job traced to
  the four files above; or
- first restore the gate with a small, separate commit that fixes the 20 type
  errors in those four test files, then push a green tree; or
- hold the push.

This phase deliberately did not touch those four files, because a phase commit
should not silently absorb another phase's debt and the fix belongs in a commit
of its own.

## 1. Identity Foundation (6.12-A)

`backend/app/security/` is a new, self-contained package. It does not import
`app.models` (which would create a cycle), so the identity tables are declared
in `security/models.py` and re-exported from `app/models/__init__.py`.

- **User** — `id` (UUID), `username` (unique), `email` (optional, unique),
  `password_hash`, `status` (`ACTIVE`/`DISABLED`, `StrEnum` plus a database
  check constraint), `created_at`, `updated_at`. Username and email are
  normalised by `strip().casefold()`, so uniqueness is a plain constraint rather
  than a functional index.
- **Password storage** — bcrypt only. Shipped cost factor 12, tests run at 4 and
  a test asserts the shipped value separately, so the two cannot drift. MD5,
  SHA-1 and plaintext are absent from the module, not merely unused.
- **Password policy** — `>=12` characters, `<=72` bytes (bcrypt truncates beyond
  this, which would make a longer password mean something other than what was
  typed), and not equal to the username.
- **Timing equalisation** — a missing user is verified against a dummy hash, so
  "no such user" is not measurably faster than "wrong password".
- **Migration** — `20260924_09_phase6_12_security.py` creates the five tables,
  adds four nullable columns to `audit_events`, and seeds the roles,
  permissions, and grants. `downgrade` reverses all of it.

## 2. Authentication API (6.12-B)

`backend/app/api/auth.py`, mounted at both `/api/v1/auth` and `/api/auth`.

| Route | Behaviour |
|---|---|
| `POST /auth/register` | Creates an identity. Self-service always receives `VIEWER`; `roles` in the payload is honoured only for a caller holding `user.manage`, because otherwise registration is a privilege-escalation endpoint. Switchable off by configuration. |
| `POST /auth/login` | Verifies credentials and returns an access token plus the identity. Audited on both outcomes. Rate-limited before any verification runs. |
| `GET /auth/me` | Returns the caller's identity and its **effective** permissions, which is what lets the interface withhold an action it would only be refused for. |

Tokens are HS256 JWTs with `sub`, `user_id`, `roles`, `iat`, `exp`. Verification
rejects each failure separately: `alg: none`, wrong secret, malformed structure,
missing required claim, `typ` other than `access`, non-UUID subject, and expiry
checked against an injectable clock. An unknown username and a wrong password
produce a byte-identical `401 INVALID_CREDENTIALS`; the difference exists only in
the audit row.

## 3. RBAC Authorization (6.12-C)

The vocabulary is code (`app/security/rbac.py`), the grants are data (four
tables, seeded by migration, read on every request). The consequence that
matters: revoking a grant takes effect on the **next request**, not the next
deployment, because authorization never reads the roles claim out of the token.

`*` is reserved for `ADMIN` and is an exact membership test, not a glob, so a
permission named `incident.*` could never be mistaken for wildcard authority.

**25 governed routes** now declare `require_permission(...)` across incidents,
workflows, approvals, and work orders. The complete matrix is in
`docs/SECURITY_MODEL.md`. `approval.review` is new: it separates reading a
decision from making one, and the approval state machine itself is untouched.

A walk of the live route table (`tests/security/test_route_coverage.py`) asserts
the matrix exactly, cross-checks the walk against the OpenAPI schema so it
cannot pass by seeing too little, and asserts that the legacy `/api` mirror
enforces precisely what `/api/v1` enforces.

## 4. Audit Enhancement (6.12-D)

`audit_events` gained `actor_user_id`, `resource_id`, `ip_address`, and
`user_agent`, all nullable, so existing writers and rows are unaffected.

Recorded this phase: sign-in succeeded, sign-in failed (with the reason and no
user id), registration, permission denied (with the required permission, method,
and path), and the incident, workflow, and approval transitions — in one shape,
`{actor, action, resource, resource_id, status}`.

The acting identity reaches the writer through a request-scoped
`SecurityContext` published into a `ContextVar` by the auth dependency and reset
by the correlation middleware at the start of every request, so no identity can
leak across requests and no call signature has to thread the principal.

Two audit conventions coexist and are documented in `app/repositories/audit.py`:
legacy writers put an identifier in `resource`, security events put the type in
`resource` and the instance in `resource_id`. Existing rows were not rewritten.

## 5. Security Boundary (6.12-E)

| Condition | Status | Code |
|---|---|---|
| No usable identity | `401` | `AUTHENTICATION_REQUIRED`, `INVALID_TOKEN`, `TOKEN_EXPIRED`, `INVALID_CREDENTIALS`, `ACCOUNT_DISABLED` |
| Identity present, permission missing | `403` | `PERMISSION_DENIED` + `details.required_permission` |
| Too many failed sign-ins | `429` | `LOGIN_RATE_LIMITED` + `details.retry_after_seconds` |
| No signing secret configured | `503` | `SECURITY_NOT_CONFIGURED` |

Login is rate limited at 5 failures per 60 seconds per source address. The
source address is the socket peer: `X-Forwarded-For` is deliberately not
trusted, since it is client-supplied and trusting it would let an attacker pick
their own bucket or forge the address written to the audit trail. The limiter
**fails open** when Redis is unreachable, and logs that it did; this is recorded
as a known limitation rather than hidden.

## 6. Secret Governance (6.12-F)

`scripts/security_scan.py` sweeps every version-controlled file with a scannable
suffix for credential-shaped assignments (`*_API_KEY`, `*_PASSWORD`, `*_TOKEN`,
`*_SECRET`) and credentials embedded in URLs. A value is only reported when it
clears a Shannon-entropy floor (3.0 bits/char) and a minimum length, so
`POSTGRES_PASSWORD=change-me-in-dotenv` passes while a real key does not.

Two corrections were made during this phase, both driven by the scanner
reporting its own new tests:

- The identifier rule now also treats `SCREAMING_SNAKE` names such as
  `SECURITY_BOOTSTRAP_PASSWORD` as labels rather than secrets. The clause
  requires an underscore, so a separator-free base32 secret is still reported;
  a test pins exactly that boundary.
- The suite's own fixtures were rewritten to `dummy-`-prefixed placeholders and
  run-time-assembled values, so no credential-shaped literal is tracked and the
  repository sweep stays strict with zero exemptions. Note that this defect was
  invisible until the files were committed: `scan_repository` lists files via
  `git ls-files`, so untracked files are not scanned.

The scan runs in the CI `deployment` job and exits non-zero on any finding.
`scripts/create_admin.py` bootstraps the first administrator, reading the
password from `SECURITY_BOOTSTRAP_PASSWORD` or an echo-off prompt, never from
`argv`.

## 7. Frontend Security (6.12-G)

- **Token storage** (`src/authStorage.ts`) — `sessionStorage` behind a
  `TokenStorage` interface, with an in-memory fallback when storage is blocked,
  so sign-in still works in private mode. Session scope rather than persistent,
  because an operator token that survives a browser restart survives on a shared
  plant terminal too.
- **Auth Context** (`src/auth.tsx`) — three states: `anonymous`, `restoring`,
  `authenticated`. The shell is not painted in `restoring`, because a shell
  painted before the identity is known would flash actions the operator may not
  have.
- **Route guard** — `RequireAuth` as a layout route, preserving the attempted
  location so sign-in returns the operator to where they were going.
- **Sign-in page** — posts credentials, stores the token, then reads authority
  back from `GET /auth/me` rather than from the sign-in response. No
  self-service sign-up surface.
- **Page permissions** — a `VIEWER` sees a readable incident with no lifecycle
  buttons and a line explaining that their role may read but not act; an
  identity without `approval.review` sees the plan and evidence but no decision
  form, and the approval state is not misreported as the reason.
- **Backend re-verification** — a `401` anywhere clears the token and collapses
  the session in one place; a `403` does not, because it means the identity is
  fine and the permission is missing. A test asserts a server refusal still
  surfaces when the action was offered anyway.

## 8. Documentation (6.12-H)

- `docs/SECURITY_MODEL.md` — identity, authorization, the full enforcement
  matrix, the boundary table, audit format, secret governance, the operator
  interface, configuration, and an explicit non-goals and known-limitations
  section (no SSO/OAuth/OIDC/SAML, no enterprise IAM, no Zero Trust, no MFA, no
  refresh tokens or revocation list, no cloud/Kubernetes IAM).
- `docs/CONFIGURATION.md` — security section, including why
  `SECURITY_JWT_SECRET` is intentionally not a required key.
- `.env.example` — five security variables with an empty `SECURITY_JWT_SECRET`
  that fails closed.
- `.github/workflows/ci.yml` — secret scan step in the `deployment` job; docs
  job asserts `docs/SECURITY_MODEL.md` exists.

## 9. Defects Found and Fixed

1. **Two governed routes were open.** `POST /incidents` and
   `GET /incidents/{incident_id}` were reachable with no identity at all: the
   permission dependency existed and was imported, but had never been attached
   to those two routes. Found while writing the enforcement matrix, not by a
   test. Both are now gated, and `tests/security/test_route_coverage.py` makes
   the next omission a build failure rather than a silent hole.
2. **The scanner reported its own fixtures**, once they became tracked. Fixed by
   making the fixtures recognisable placeholders and assembling realistic values
   at run time, rather than by exempting paths.
3. **The scanner flagged an environment-variable name** as a credential. Fixed
   with a narrow rule and a test pinning its boundary.
4. **`CounterStore` declared three Redis operations and the limiter called
   four.** A protocol that omits a method the implementation uses is a typing
   hole; `get` was added with its honest return union.
5. **Three repository methods returned `Any`** from `AsyncSession.scalar`. Fixed
   with `cast`, following the convention already used in
   `app/repositories/`.
6. **14 ruff errors** (12 × `N818`, 2 × `E402`) from the first pass: the error
   taxonomy was renamed to the `*Error` suffix the rest of the codebase already
   uses, and module-level imports were moved to the top.

## 10. Tests

New backend suites under `backend/tests/security/` (142 tests):

| File | Covers |
|---|---|
| `test_password_and_tokens.py` | bcrypt cost, salting, policy, dummy-verify; token round-trip, expiry boundary, wrong secret, tampering, `alg: none`, missing claims, non-access type |
| `test_authentication.py` | registration and its role-escalation refusal, sign-in, indistinguishable failures, disabled account, `/auth/me` shape and no password echo, stored hash shape, status check constraint |
| `test_rbac_enforcement.py` | `401` vs `403`, `ADMIN` reaches the route body, `OPERATOR` limited, `VIEWER` read-only, revocation effective on the next request, disabled identity invalidates a token |
| `test_audit_security.py` | sign-in success/failure rows, denial row written before the route body, lifecycle attribution through the security context, unified shape |
| `test_rate_limit.py` | five-failure block, window arming once, reset on success, per-origin isolation, fail-open on a missing and on a broken store |
| `test_rbac_vocabulary.py` | seeded grants equal the code table, `VIEWER` subset of `OPERATOR` and write-free, wildcard is an exact match |
| `test_route_coverage.py` | the matrix, the OpenAPI cross-check, the `/api` mirror, the vocabulary |
| `test_security_scan.py` | real secrets reported (assignment and URL), placeholders and code pass, CLI exit codes, and the repository sweep |

New frontend suite `frontend/src/security.test.tsx` (21 tests): token storage,
credential attachment, `401` versus `403`, sign-in, the route guard and session
restoration, page-permission gating on incidents and approvals, and shell
sign-out.

Two existing frontend suites were updated to render under a settled session, and
`App.test.tsx` now asserts the guard behaviour instead of assuming an open shell.

## 11. Validation Results (all executed this session)

| Suite | Result |
|---|---|
| backend `pytest` (DB-backed, PostgreSQL + pgvector @127.0.0.1:65179) | **597 passed, 94 skipped** (from 591/94 at base) |
| backend `pytest tests/security` | **142 passed** |
| `ruff check` / `ruff format --check` | **clean** (198 files) |
| `mypy app tests` | **20 errors in 4 files**, none in this phase's code; **identical 20 errors measured on an isolated worktree at the base commit `2379224`**, so this phase introduces none |
| frontend `npm test` / `npm run lint` / `npm run build` | **56 passed (10 files) / clean / clean** |
| `alembic heads` / `upgrade head` / `check` | `20260924_09 (head)` / applied / **"No new upgrade operations detected"** |
| `python scripts/security_scan.py` | **clean, 0 findings**, exit 0 |
| `python scripts/validate_env.py .env.example --mode example` | **pass** |
| remote CI | **not verified** (see section 0) |

## 12. Git

- Commit `21bb321` — `feat: add security governance foundation` on `main`, based
  on `2379224`. 55 files changed, 6593 insertions, 82 deletions. No tag, no
  release.
- Not pushed. Local `main` is 6 commits ahead of `origin/main` (`2c2f216`), all
  fast-forwardable; 5 of those commits belong to Phases 6.9-A through 6.11.
- No history was rewritten except the message and content of this phase's own
  single, unpushed commit. No `reset --hard`, no force push, no `git clean`.

## 13. Boundary Statement

Business flows are untouched. The Agent graph, prompts, safety policy, approval
state machine, and WorkOrder state machine behave exactly as before; this phase
answers "may this caller do this?" before the existing code runs, and records
who did it. The system still recommends and a human still approves, now with an
authenticated identity behind that approval.

The governed surface is deliberately partial. Alarms, alarm rules, assets,
device configuration, connectivity, and observability still use the descriptive
`X-Actor` header, and `app/api/dependencies.py` records that boundary in the
source. Until those routes are migrated, treat the audit actor on those paths as
descriptive rather than authenticated. This is stated as a limitation in
`docs/SECURITY_MODEL.md` rather than left for someone to discover.

**Stopped here.** No work on Phase 6.13, Kubernetes, Cloud, SSO, Enterprise IAM,
or Phase 7.
