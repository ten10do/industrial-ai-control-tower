# Phase 6.6 Release Final Report

Date: 2026-09-22
Branch: `main`
Scope: DISC-1 authorization, release wrap-up, push verification
Decision: **RELEASE BLOCKED ON ONE UNRELATED PRE-EXISTING CI DEFECT** (see DISC-2)

## Status summary

| Item | Result |
|---|---|
| DISC-1 (ADR assertion) root cause identified | YES |
| DISC-1 fix applied and committed | YES (`2f420e1`) |
| DISC-1 local verification (docs job reproduced) | PASS |
| DISC-1 real GitHub Actions verification | PASS (docs job green) |
| Phase 6.6 commit pushed | YES (`e8006857`) |
| Working tree clean | YES |
| `local main == origin/main` | YES (`2f420e1f6a9879fcc451e5981c75c34f64bab1c0`) |
| Full CI workflow green | **NO** | 
| Blocker | DISC-2, pre-existing `frontend` build failure, not caused by Phase 6.6 |

The requested DISC-1 repair is complete and verified on real GitHub Actions. The CI workflow as a
whole still reports `failure` because of a separate, pre-existing defect in the `frontend` job that
was previously masked by the `docs` job failing at the same time. That defect is recorded as
DISC-2. It is outside the authorized scope of this task, so it was diagnosed but not repaired.

## DISC-1: root cause

The `docs` job in `.github/workflows/ci.yml` asserted an exact ADR file count:

```sh
adr_count=$(ls docs/adr/ADR-*.md 2>/dev/null | wc -l)
if [ "$adr_count" -ne 10 ]; then
  echo "Expected 10 ADRs, found $adr_count"
  exit 1
fi
```

ADR-011 was introduced in Phase 4 (commit `0a6ed71`). The repository has carried 11 ADR files ever
since, while the assertion still demanded exactly 10. The `docs` job therefore failed from Phase 4
onward, independent of any later work.

Two independent facts made this invisible for a long time:

1. The other four jobs (`backend`, `frontend`, `simulator`, `ml`) passed, so the run was red for a
   reason already attributed to other work.
2. `ls ... | wc -l` is not the same as "the ADR set is intact". It counted files without checking
   numbering, headings, or uniqueness, so the assertion carried no structural meaning to preserve.

Neither Phase 6.6 nor this release added or removed an ADR.

## DISC-1: actual fix

The exact-count assertion was replaced by a structural validation of the same intent. The change
is confined to the `docs` job's `run` script in `.github/workflows/ci.yml`, 37 insertions and 3
deletions, no new file, no new dependency, no new tool. Everything runs on POSIX `sh` utilities
already available on the runner (`basename`, `sed`, `printf`, `head`, `grep`).

The replacement asserts four properties:

1. **Existence.** At least one `docs/adr/ADR-*.md` file exists. An unmatched glob is detected with
   `[ ! -e "$adr" ]` and fails with `No ADR files found under docs/adr`.
2. **Three-digit filenames.** Each file's numeric part must match `[0-9][0-9][0-9]`, so a name like
   `ADR-1.md` cannot slip into a set that is otherwise zero-padded.
3. **Contiguity.** Numbers must run `ADR-001`, `ADR-002`, ... with no gap. The expected value is
   generated with `printf '%03d'` and compared as a string, which sidesteps the octal trap that
   `$((...))` would introduce for zero-padded values such as `008`.
4. **Heading agreement.** Line 1 of each file must begin with `# ADR-NNN` matching its own filename,
   so a renamed or copy-pasted file is caught.

A floor of `ADR_MIN_COUNT=11` is retained on top of those checks. The asymmetry is deliberate:
additions need no edit to `ci.yml`, while an accidental deletion of the most recent ADR still fails.
The floor is a lower bound, not an expectation, which is what makes the new check survive future
legitimate ADRs.

The required-document checks that preceded the ADR block (`README.md`, `docs/API_CONTRACT.md`, and
the other seven paths) were left untouched. A verification step asserts they are still present.

## DISC-1: local verification

### Workflow parsing and structure

`.github/workflows/ci.yml` was parsed as YAML and asserted to still contain exactly the five jobs
`backend`, `frontend`, `simulator`, `ml`, `docs`. The documentation step was extracted from the
parsed document and executed with bash, so the verification ran the shipped script rather than a
retyped copy.

### docs job executed from the repository root

```text
exit=0 | Documentation validation passed
```

### Synthetic cases proving the new check is not vacuous

The same extracted script was executed against eight fabricated trees, each containing the nine
required documents plus a controlled ADR set:

| Case | Expected | Observed | Message |
|---|---|---|---|
| Valid contiguous set of 11 (current shape) | PASS | PASS | `Documentation validation passed` |
| Valid set of 12 (a future legitimate ADR added) | PASS | PASS | `Documentation validation passed` |
| Numbering gap, ADR-003 absent | FAIL | FAIL | `ADR numbering is not contiguous: expected ADR-003.md, found docs/adr/ADR-004.md` |
| Mismatched heading on ADR-007 | FAIL | FAIL | `ADR docs/adr/ADR-007.md must start with a '# ADR-007' heading` |
| Undersized set of 5 | FAIL | FAIL | `Expected at least 11 ADRs, found 5` |
| Non three-digit filename `ADR-1.md` | FAIL | FAIL | `ADR numbering is not contiguous: expected ADR-001.md, found docs/adr/ADR-002.md` |
| Three-digit format branch isolated (`ADR-1.md` only) | FAIL | FAIL | `ADR filename must use a three-digit number: docs/adr/ADR-1.md` |
| No ADR files at all | FAIL | FAIL | `No ADR files found under docs/adr` |

The second row is the specific regression this change exists to prevent: adding a 12th ADR leaves
the job green, where the old assertion would have turned it red.

### Other required checks

| Check | Command | Result |
|---|---|---|
| Whitespace and conflict markers | `git diff --check` | clean |
| Documentation structure | `docs` job script | PASS |
| Working tree | `git status --short` | empty |

No Markdown linter is configured in this repository (no `.markdownlint*`, no `.mdlrc`), so the
`docs` job script is the repository's documentation validation contract.

## GitHub Actions result

`gh` CLI is installed but not authenticated in this environment (`gh auth status` reports no logged
in hosts), so workflow results were read from the public GitHub REST API instead. The repository is
public, and the API accepted unauthenticated reads.

Run for the first pushed commit of this release (`2f420e1`, the DISC-1 fix):

| Field | Value |
|---|---|
| Run ID | `35692016246` |
| Head SHA | `2f420e1f6a9879fcc451e5981c75c34f64bab1c0` |
| Event | `push` |
| Created | 2026-09-22T05:46:17Z |
| Conclusion | `failure` |
| URL | https://github.com/ten10do/industrial-ai-control-tower/actions/runs/35692016246 |

Run for the final release HEAD (`af0bbd0`, which adds only this Markdown report):

| Field | Value |
|---|---|
| Run ID | `35692397114` |
| Head SHA | `af0bbd065f8f6657900dc1e55df84769d8d70dc2` |
| Event | `push` |
| Created | 2026-09-22T05:52:08Z |
| Conclusion | `failure` |
| URL | https://github.com/ten10do/industrial-ai-control-tower/actions/runs/35692397114 |

Per-job results, identical in shape across both runs:

| Job | `2f420e1` | `af0bbd0` |
|---|---|---|
| `docs` | **success** | **success** |
| `backend` | **success** | **success** |
| `simulator` | **success** | **success** |
| `ml` | **success** | **success** |
| `frontend` | **failure** (`Build`) | **failure** (`Build`) |

The `docs` job is green on real GitHub Actions in both runs, which is the authoritative
confirmation that DISC-1 is fixed. The remaining red job is DISC-2 in both runs.

Historical comparison, from the same API, showing that the two failures are independent and that
the `frontend` failure predates Phase 6.6:

| Run | Head SHA | Commit subject | `docs` | `frontend` |
|---|---|---|---|---|
| 35678421771 | `cff4f3cc` | pre Phase 6.6 | failure | failure |
| 35683381316 | `37f7c32f` | pre Phase 6.6 | failure | failure |
| 35685115313 | `a12cd642` | pre Phase 6.6 | failure | failure |
| 35692016246 | `2f420e1f` | this release | success | failure |

`docs` flipped from failure to success in the release run. `frontend` failed identically in all four
runs, including the three whose trees contained no Phase 6.6 frontend code.

## DISC-2: pre-existing frontend build failure (not fixed, authorization requested)

**Symptom.** The `frontend` job's `Build` step fails on `npm run build`:

```text
vite.config.ts(7,3): error TS2769: No overload matches this call.
  The last overload gave the following error.
    Object literal may only specify known properties, and 'test' does not exist in type 'UserConfigExport'.
```

**Root cause.** `frontend/vite.config.ts` imports `defineConfig` from `vite` and then passes
Vitest's `test` key:

```ts
/// <reference types="vitest" />
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.ts',
  },
})
```

The legacy `/// <reference types="vitest" />` augmentation is what used to widen `vite`'s
configuration type enough to accept `test`. With the resolved versions in this repository
(`vite@8.3.0`, `vitest@5.0.1`) that augmentation no longer widens `UserConfigExport`, so `test` is
rejected. `frontend/package-lock.json` was last modified 2026-09-21T16:06:53, which is later than
`vite.config.ts` (2026-09-17T13:26:50). The dependency move tightened the type beneath a config file
that was never updated to match.

**Why it looked green locally.** `npm run build` is `tsc -b && vite build`, and `tsc -b` is
incremental. A stale `frontend/tsconfig.node.tsbuildinfo` recorded a previously passing state for
`vite.config.ts`, so `tsc -b` considered the project up to date and skipped re-checking it. Forcing
a full rebuild reproduced the CI error exactly:

```text
$ npx tsc -b --force
vite.config.ts(7,3): error TS2769: No overload matches this call.
tsc_exit=2

$ npm run build
vite.config.ts(7,3): error TS2769: No overload matches this call.
build_exit=2
```

The local and CI results now agree. The earlier agreement was an artifact of an incremental cache,
not of a real difference between the environments. Node versions were ruled out: local
`node v22.22.2` and CI `node-version: '22'` share a major version.

**Why the Phase 6.6 Docker frontend image built successfully.** The Dockerfile builds from the
`frontend` directory and copies the whole context:

```dockerfile
COPY . .
RUN npm run build
```

`docker build -t ... frontend` uses `frontend/` as the context root, and Docker only reads
`.dockerignore` from that context root. There is no `frontend/.dockerignore`, so the root
`.dockerignore` (which excludes `node_modules/` and `frontend/dist/`) never applied to this build.
The 120.1 MB build context therefore carried the host's stale `frontend/tsconfig.node.tsbuildinfo`
into the image, and the incremental build skipped the failing check inside the container as well.

With that file now recording the error, the same Docker build fails identically:

```text
Step 5/11 : COPY . .
Step 6/11 : RUN npm run build
vite.config.ts(7,3): error TS2769: No overload matches this call.
The command '/bin/sh -c npm run build' returned a non-zero code: 2
docker_build_exit=2
```

**Assessment.** Two defects are entangled here. The first is the one-line type/config mismatch. The
second is that the frontend build context has no `.dockerignore`, so a local developer's build
cache is copied into the image and can mask a broken build. Fixing only the first would leave the
second in place.

**Proposed fix (not applied).** Import `defineConfig` from `vitest/config` instead of `vite`:

```ts
import { defineConfig } from 'vitest/config'
```

This is the documented Vitest 5 / Vite 8 arrangement. A `.dockerignore` for the frontend context
excluding `node_modules`, `dist`, and `*.tsbuildinfo` would close the second defect. Both are
changes to frontend code and configuration, which the current authorization does not cover. They
were deliberately not made.

**Impact on this release.** The frontend container image cannot be rebuilt from a clean checkout
until DISC-2 is fixed, and the CI workflow cannot report green.

## Correction to PHASE_6_6_FINAL_REPORT.md

The Phase 6.6 report was committed and pushed as the release record for that phase and was not
rewritten. One row in it is now known to be environment-dependent, and is corrected here so the
record is not read as a stronger claim than the evidence supports.

| Phase 6.6 report row | As written | Actual |
|---|---|---|
| Regression, Frontend build | `npm run build` PASS | Exits 0 only while a stale `tsconfig.node.tsbuildinfo` is present; fails with `TS2769` in a clean state and in CI |
| Regression, Docker frontend build | `docker build frontend` PASS | Passed only because the stale cache was copied into the image; fails identically now |
| Image packaging (frontend) | asset hashes matched local output | Still true, but the local output at that moment came from the same masked incremental build |

The remaining Phase 6.6 results (backend, ML, simulator, frontend tests and lint, schema drift,
Docker backend image, live database integrity) are unaffected and were re-confirmed in this task.

## Git

| Item | Value |
|---|---|
| Branch | `main` |
| Phase 6.6 commit | `e8006857af4fd9946f160f0139fb9dfb0923b5e8` (`feat: add agent observability layer`) |
| DISC-1 fix commit | `2f420e1f6a9879fcc451e5981c75c34f64bab1c0` (`fix: update ADR documentation CI check`) |
| Release report commit | `af0bbd065f8f6657900dc1e55df84769d8d70dc2` (`docs: add phase 6.6 release final report`) |
| Final tip | one further documentation commit recording the `af0bbd0` CI run; the tip hash is obtained with `git log -1 --format=%H` because it contains this file |
| Working tree | clean |
| Push | performed for all of the above |

Remote synchronization was verified two ways, after the `af0bbd0` push:

```text
$ git ls-remote origin refs/heads/main
af0bbd065f8f6657900dc1e55df84769d8d70dc2	refs/heads/main

$ git rev-parse HEAD origin/main
af0bbd065f8f6657900dc1e55df84769d8d70dc2
af0bbd065f8f6657900dc1e55df84769d8d70dc2

$ git status -sb
## main...origin/main
```

The authoritative check is `git ls-remote`, which reads the value GitHub actually holds. The local
tracking check was verified at the same hash, then the final documentation commit advanced both
sides together.

One environment note worth recording. The first push attempt under the default Git transport
protocol failed with `bash.exe: line 1: /mingw64/bin/git: Interrupted system call` and pushed
nothing. Re-running with `-c protocol.version=0` succeeded. The same flag was needed for
`ls-remote` and `fetch` network calls. Additionally, `git fetch` and `git update-ref` reported
success while silently failing to materialize `refs/remotes/origin/main`, because the
`refs/remotes/origin/` directory did not exist. A plain file write into
`.git/refs/remotes/origin/main` after `mkdir -p` restored it. The network read path was never
affected.

## Scope boundary

DISC-1 is fixed, verified locally, and verified on real GitHub Actions. Phase 6.6 is pushed. The
release is recorded as **blocked on DISC-2 pending authorization**, since a green CI workflow was
requested and cannot be achieved without touching frontend code.

Not started, as instructed: Phase 7, Kubernetes, Deployment, Cloud Infrastructure, v1.4.0.

Phase 7: NOT_STARTED

## Requested authorization

1. Fix DISC-2 with the one-line `vitest/config` import in `frontend/vite.config.ts`.
2. Add `frontend/.dockerignore` excluding `node_modules`, `dist`, and `*.tsbuildinfo`.
3. Re-run CI after those changes to confirm the whole workflow is green.

Alternatively, DISC-2 can be deferred and carried into the next phase as a known blocker.
