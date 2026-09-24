# Phase 6.12 Final Report — Security & Governance Foundation

**Status**: `PHASE_6_12_COMPLETE` — remote CI green, run `35956414254`, 6/6 jobs
**Base commit**: `2379224` (Phase 6.11) · **Branch**: main
**Phase commits**: `21bb321`, `b3061ea`, `d041ef3`, `430d999`, `e675b53`
**Remote**: `origin/main` fast-forwarded `2c2f216` (6.8) → `e675b53`
**Constraint compliance**: no business-flow, Agent, Workflow Graph, Approval
state-machine, WorkOrder, ML, or RAG changes; no Cloud, Kubernetes, SSO,
Enterprise IAM, OAuth, or Zero Trust work; no tag, no release; stopped before
Phase 6.13.

## 0. Remote state, CI outcome, and what the local gates could not see

Every implementation task and every local gate of this phase is complete and
green, and the phase is now `PHASE_6_12_COMPLETE`. Reaching that state took
three CI runs and two follow-up commits, because two of the failures could not
be reproduced locally. Both are recorded here in full: the value of this section
is the failure mode, not the success.

**The first push carried eight commits at once**, as a fast-forward. Five of them
belong to earlier phases and had never been pushed: `2379224` (6.11), `4a41c18`
(6.10), `c5d852f` (6.9-C), `e5f58e7` (6.9-B) and `112d879` (6.9-A). The other
three were this phase's implementation (`21bb321`), its report (`b3061ea`), and
the gate fix described below (`d041ef3`). Two further commits, `430d999` and
`e675b53`, followed once CI exposed what the local gates had missed. The full
list is in section 12.

`origin/main` was at `2c2f216` (6.8), a strict ancestor of local `main`, so the
push was a fast-forward with no rewriting. Because those earlier phases had never
been pushed, their CI gate had never been confirmed, which is why publishing them
was put to the operator as a decision rather than taken unilaterally.

**The push was held first, because `mypy` was not clean.** A fresh-cache
`mypy app tests` run on an isolated worktree at `2379224` (the unmodified Phase
6.11 base) reported **20 errors in 4 files**, and the identical 20 appeared
after this phase. All four files belonged to earlier phases:

```
tests/test_deployment_foundation.py          type-arg, no-untyped-def, arg-type,
                                             union-attr, index, unused-ignore
tests/incidents/test_deployment_roundtrip.py import-untyped, truthy-function
tests/incidents/test_platform_reliability.py unused-ignore (x3)
tests/test_platform_reliability.py           misc
```

`backend/requirements-dev.txt` pins `mypy>=1.10.0` without an upper bound, and
CI was later confirmed to resolve mypy 2.3.1, the same build as local. The
`backend` job runs `mypy app tests`, so this debt would have turned that job red
for reasons that pre-date this phase. It was fixed in its own commit, `d041ef3`,
scoped to the four test files: parameterise `CompletedProcess`, annotate two
generator fixtures, narrow `importlib` spec/loader, type the parsed
deployment-check JSON, and drop four `type: ignore` comments plus a dead import
that mypy 2.x no longer needs.

For the record, `PHASE_6_10_FINAL_REPORT.md` and `PHASE_6_11_FINAL_REPORT.md`
both claim `mypy` clean. That claim is not reproducible against the tree they
describe. The explanation is a mypy version change, since every failing code is
version-sensitive (`index` on `object`, `unused-ignore`, `type-arg`), rather than
a false claim at the time. The debt was real and belonged to 6.10/6.11 test
files, which is where the fix was applied.

### 0.1 Three CI runs, and why the first two failed

The naive expectation was that fixing the 20 `mypy` errors would make CI green.
It did not. Two further failures surfaced, and neither was reproducible locally.
Both are worth recording, because the pattern is the same in each case: **the
local environment was not the CI environment, and every local gate was green.**

| Run | Commit | Outcome |
|---|---|---|
| `35954114086` | `d041ef3` | **fail** — `backend` at *Type check*, `deployment` at *unit tests* |
| `35955921527` | `430d999` | **fail** — `backend` at *Test*, `deployment` at *unit tests* |
| `35956414254` | `e675b53` | **pass** — 6/6 jobs |

**Run 1: nine `mypy` errors that had nothing to do with `mypy`.** The Type check
step failed with 9 `import-not-found` / `no-any-return` errors, and the log
showed CI resolving mypy 2.3.1, the same build as local. The cause was that four
imported packages were never declared anywhere:

- `PyJWT` and `bcrypt`, imported by `app/security/tokens.py` and
  `app/security/passwords.py`, appeared in neither `pyproject.toml` nor
  `requirements.txt`. Because `backend/Dockerfile` installs `requirements.txt`,
  the built image could not have imported `app.security` at all. This is the most
  serious defect this phase produced, and no local gate could see it.
- `prometheus-client` was in `requirements.txt` but missing from
  `pyproject.toml`, so the `pip install -e .` in the `backend` job never
  installed it, even though `app/platform_observability/metrics.py` imports it.
- `pgserver` was never declared; it is imported inside a `try/except ImportError`
  guard, which makes its absence a supported state.

The local `.venv` happened to have all four packages installed by hand, which is
exactly why every local gate passed. A hand-grown environment hides an undeclared
dependency. The fix is `430d999`.

Run 1's `deployment` job failed with `No module named pytest`: its step installed
`requirements.txt` (runtime dependencies only) and then invoked pytest. That job
had never run on the remote before, because 6.11 was among the unpushed commits,
so this pre-existing defect was surfacing for the first time.

**Run 2: the mypy debt was fixed, and a host-dependent test was exposed.** Type
check went green, and the remaining failures were one and the same test in two
jobs, `test_deployment_check_passes_against_healthy_backend`, with the report:

```
{'status': 'fail', 'docker': 'ok',
 'services': {'postgres': 'absent', 'redis': 'absent', 'mosquitto': 'absent', ...},
 'checks': {'health': 'ok', 'ready': 'ok', 'metrics': 'ok', ...}}
```

That report is correct. `deployment_check.py` verifies that all five services
are running; a GitHub runner has a Docker daemon but no compose services, so the
container dimension legitimately fails. The test asserted a clean pass, which
only holds on a host without a Docker daemon. The assertions depended on the
machine, not on the code under test, which is why Windows was green and CI was
red. The fix is `e675b53`, which passes `--docker-bin <interpreter>` so the probe
deterministically reports `DOCKER_DAEMON_UNAVAILABLE` and is tolerated, and adds
a unit test pinning the live-daemon-with-absent-services verdict.

**Run 3 is green and is the release basis.** Every job passes on `e675b53`.

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
7. **`PyJWT` and `bcrypt` were imported but never declared.** Found by the first
   remote CI run, not by any local gate. `requirements.txt` is what
   `backend/Dockerfile` installs, so the container image would have failed to
   import `app.security` at all. Fixed in `430d999` by declaring both in
   `pyproject.toml` and `requirements.txt`.
8. **`prometheus-client` was in `requirements.txt` but not in `pyproject.toml`.**
   The two manifests had silently diverged, so `pip install -e .` never installed
   it. Fixed in the same commit, restoring the two files to agreement.
9. **`test_deployment_check_passes_against_healthy_backend` depended on the
   host having no Docker daemon.** It asserted a clean pass, which a runner with
   a live daemon and no compose services cannot produce. Fixed in `e675b53`,
   together with a new unit test that pins the live-daemon verdict.
10. **The `deployment` job invoked pytest without installing it.** A pre-6.11
    defect that had never run on the remote, because 6.11 was among the unpushed
    commits. Fixed in `430d999`.

The last four share one root cause, and it is the most transferable lesson of
this phase: **a hand-grown local environment is not evidence about CI.** The
local `.venv` had `PyJWT`, `bcrypt`, `prometheus-client` and `pgserver` installed
by hand, and Windows has no Docker daemon. Every local gate was green while CI
was red. Reproducing the CI install in a fresh venv, and reasoning about what the
host provides, is what closed the gap.

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

`backend/tests/test_deployment_foundation.py` is not a new suite, but CI added one
test to it: the live-daemon-with-absent-services case that run 2 exposed. It now
covers both directions of the container dimension instead of assuming the host has
no Docker.

## 11. Validation Results

Every figure below was measured, not inherited. Two environments are reported
separately on purpose: the local one, which runs the whole suite against a real
PostgreSQL, and a fresh venv that reproduces the CI install, which is the only
environment that could have caught defects 7 and 8 above.

**Local, with PostgreSQL 16 + pgvector (three opt-in database variables set).**
The `_TEST_DATABASE_URL` variables are per-suite and each suite drops the
database it was given, so all three point at separate databases.

| Suite | Result |
|---|---|
| backend `pytest` (full, `ALARM_` + `ASSETCONFIG_` + `OBSERVABILITY_` set) | **691 passed, 0 skipped** |
| backend `pytest` (`tests/incidents` alone) | 211 passed |
| backend `pytest` (`tests/security` + observability integration) | 143 passed |
| `alembic heads` / `upgrade head` / `current` / `check` | `20260924_09` / 10 migrations applied / `20260924_09 (head)` / **"No new upgrade operations detected"** |
| frontend `npm test` / `npm run lint` / `npm run build` | **56 passed (10 files) / clean / clean** |
| `python scripts/security_scan.py` | **clean, 0 findings**, exit 0 |
| `python scripts/validate_env.py .env.example --mode example` | **pass** |

**Fresh venv reproducing the CI install (`pip install -r requirements-dev.txt`),
plus a pytest-only venv for the `deployment` job.**

| Gate | Result |
|---|---|
| `ruff check` / `ruff format --check` | **clean** (198 files) |
| `mypy app tests` | **clean, 178 source files** (was 20 errors before `d041ef3`) |
| backend `pytest`, no database (the CI condition) | **439 passed, 253 skipped, 0 failed** |
| `pytest backend/tests/test_deployment_foundation.py` from the repo root | **13 passed** |

**Remote.**

| Gate | Result |
|---|---|
| CI run `35956414254` on `e675b53` | **6/6 jobs green**: backend, deployment, docs, frontend, ml, simulator |

The earlier runs `35954114086` and `35955921527` failed; section 0.1 records what
each one exposed. The green run is the release basis for this phase.

## 12. Git

`origin/main` was fast-forwarded `2c2f216` (Phase 6.8) to `e675b53` across three
pushes: eight commits in the first, then one after each of the two CI runs that
failed. No history was rewritten, there was no divergence to reconcile, and no
`reset --hard`, no force push and no `git clean` was used anywhere in this phase.

| Commit | Subject | Change |
|---|---|---|
| `e675b53` | `test: make the deployment-check tests independent of the host's docker` | 1 file, +46/-1 |
| `430d999` | `fix: declare security and metrics dependencies` | 3 files, +17/-2 |
| `d041ef3` | `chore: restore mypy gate for phase 6.10-6.11 test files` | 5 files, +19/-14 |
| `b3061ea` | `docs: add phase 6.12 final report` | 1 file, +320 |
| `21bb321` | `feat: add security governance foundation` | 55 files, +6593/-82 |
| `2379224` | `feat: add production deployment foundation` (6.11) | earlier phase |
| `4a41c18` | `feat: add platform reliability hardening` (6.10) | earlier phase |
| `c5d852f` | `feat: implement incident center and workflow integration` (6.9-C) | earlier phase |
| `e5f58e7` | `feat: implement incident lifecycle, correlation engine, and context API` (6.9-B) | earlier phase |
| `112d879` | `feat: add alarm lifecycle foundation, rule registry, and incident correlation` (6.9-A) | earlier phase |

Net across the range: **117 files changed, 19347 insertions, 124 deletions**.

Only `21bb321` belongs to this phase's implementation; `b3061ea`, `d041ef3`,
`430d999` and `e675b53` are its report, gate restoration, and the two fixes CI
surfaced. The five earlier-phase commits were published unchanged: no phase
commit silently absorbed another phase's debt.

This report is then corrected by a trailing `docs:` commit so that the published
text matches the published state. That trailing commit re-runs all six jobs, and
its own green run is the final release basis; `e675b53` is the release basis for
the code. No tag and no release were created.

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
