# DISC-2 Final Report: Frontend Build Reliability

Date: 2026-09-22
Repository: `D:\industrial-ai-control-tower`
Branch: `main`
Base HEAD at task start: `6a9c8ef38f321c1e4280ac185f28db508e85c6dd`
Status: **PASS**

## Status summary

| Item | Result |
|---|---|
| Root cause identified | YES |
| Authorized scope respected | YES, two files only |
| Cold install (`npm ci`) | PASS |
| Forced type check (`tsc -b --force`) | PASS |
| Lint | PASS |
| Tests | PASS (17) |
| Production build | PASS |
| Docker no-cache build | PASS |
| Host cache proven excluded from context | YES (120.1 MB to 274.4 kB) |
| Container proven to type check for real | YES (poison probe failed the build as required) |
| GitHub Actions whole workflow | **success** |
| Backend regression affected | NO |
| Working tree | clean |
| `local main == origin/main` | YES |

The CI workflow is green across all five jobs for the first time since Phase 4. Two independent
defects had been keeping it red, and only the ADR assertion (DISC-1) was visible before this task.

## Root cause

Two defects were entangled.

**Defect 1: the Vite/Vitest configuration type mismatch.**

`frontend/vite.config.ts` imported `defineConfig` from `vite` while passing Vitest's `test` key:

```ts
/// <reference types="vitest" />
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  test: { environment: 'jsdom', globals: true, setupFiles: './src/setupTests.ts' },
})
```

The triple-slash reference used to widen `vite`'s configuration type enough to accept `test`. With
the versions the lockfile resolves (`vite@8.3.0`, `vitest@5.0.1`) that widening no longer reaches
`UserConfigExport`, so `tsc` rejected the key:

```text
vite.config.ts(7,3): error TS2769: No overload matches this call.
  Object literal may only specify known properties, and 'test' does not exist in type 'UserConfigExport'.
```

`frontend/package-lock.json` was last modified 2026-09-21T16:06:53, later than
`vite.config.ts` at 2026-09-17T13:26:50. A dependency move tightened the type beneath a config file
that was never updated.

**Defect 2: host build artifacts entering the Docker build context.**

`frontend/Dockerfile` builds from the `frontend` directory and copies the whole context:

```dockerfile
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
```

Docker reads `.dockerignore` only from the build context root. The build context is `frontend/`,
which had no `.dockerignore`, so the repository root `.dockerignore` never applied to this build.
The entire working tree was sent as context, including `node_modules`, `dist`, `*.tsbuildinfo`, and
the `vite.config.js` / `vite.config.d.ts` siblings emitted next to the source by the composite
`tsconfig.node.json` build.

The emitted `vite.config.js` deserves separate mention. Vite resolves `vite.config.js` before
`vite.config.ts`, so a stale emitted sibling could silently take precedence over the real
configuration.

**Why the failure was invisible locally.** `npm run build` is `tsc -b && vite build`, and `tsc -b`
is incremental. A stale `frontend/tsconfig.node.tsbuildinfo` recorded a previously passing state,
so `tsc -b` treated the project as up to date and never re-checked `vite.config.ts`. The same file
was copied into the Docker build context, so the container build skipped the check too. CI has no
such cache (fresh checkout), which is why only CI failed. Node versions were ruled out: local
`node v22.22.2` and CI `node-version: '22'` share a major version.

## Changed files

Exactly the two authorized files, 34 insertions and 1 deletion total.

| File | Change |
|---|---|
| `frontend/vite.config.ts` | `import { defineConfig } from 'vite'` becomes `import { defineConfig } from 'vitest/config'`. One line. No other edit, no refactor. The `/// <reference types="vitest" />` line was left in place. |
| `frontend/.dockerignore` | New. Excludes `node_modules`, `dist`, `.vite`, `*.tsbuildinfo`, `vite.config.js`, `vite.config.d.ts`, and local npm log files. |

Kept in the context, deliberately, because the build needs them: `package.json`,
`package-lock.json`, `tsconfig.json`, `tsconfig.node.json`, `vite.config.ts`, `eslint.config.js`,
`index.html`, `src/`, `public/`, and `nginx.conf` (copied into the serve stage from the same
context).

`vite.config.js` and `vite.config.d.ts` are excluded but `vite.config.ts` is not, because the
patterns are exact paths rather than a glob that would also match the TypeScript source.

No dependency, lockfile entry, or version was changed. No frontend business code, Agent
Observability code, LangGraph, Safety Policy, RAG, ML, Approval, WorkOrder, backend, or simulator
file was touched.

## TypeScript forced-build result

Host build artifacts were removed first, using only single-file deletions and non-recursive
`rmdir`, so no recursive delete ever ran against the repository:

```text
removed: frontend/dist/index.html
removed: frontend/dist/assets/index-pCOlkGid.js
removed: frontend/dist/assets/index-qsFgz3kp.css
removed: frontend/tsconfig.tsbuildinfo
removed: frontend/tsconfig.node.tsbuildinfo
removed: frontend/vite.config.js
removed: frontend/vite.config.d.ts
rmdir:   frontend/dist/assets, frontend/dist
```

Then the cold sequence ran with `set -e -o pipefail`, so a failing step could not be masked by a
pipeline.

```text
npx tsc -b --force
STEP2_PASS
```

No `TS2769`. The fix is sufficient on its own; no dependency change was required, so the
instruction to stop rather than upgrade dependencies was not triggered.

## npm build result

```text
--- STEP 1: npm ci ---
added 268 packages, and audited 269 packages in 3m
found 0 vulnerabilities
STEP1_PASS

--- STEP 3: npm run lint ---
STEP3_PASS

--- STEP 4: npm test ---
Test Files  6 passed (6)
     Tests  17 passed (17)
STEP4_PASS

--- STEP 5: npm run build ---
vite v8.3.0 building client environment for production...
73 modules transformed.
dist/index.html                   0.41 kB
dist/assets/index-qsFgz3kp.css   12.92 kB
dist/assets/index-pCOlkGid.js   264.08 kB
built in 236ms
STEP5_PASS
```

Asset hashes are identical to the pre-fix build (`index-pCOlkGid.js`, `index-qsFgz3kp.css`). The
change is types-only and has no effect on emitted output, which is the expected signature of a
correct type-level fix.

## Docker no-cache build result

```text
docker build --no-cache -t iac-tower-frontend:disc2 frontend
Step 5/11 : COPY . .
Step 6/11 : RUN npm run build
> tsc -b && vite build
vite v8.3.0 building client environment for production...
73 modules transformed.
built in 134ms
Successfully built d0d198642103
Successfully tagged iac-tower-frontend:disc2
docker_build_exit=0
```

The build succeeded while the host simultaneously held `node_modules` (125 MB), `dist` (277 kB),
`tsconfig.tsbuildinfo`, `tsconfig.node.tsbuildinfo`, `vite.config.js`, and `vite.config.d.ts`. Two
independent checks establish that this success was not produced by host artifacts.

**Evidence A, build context size.** The same build previously reported a 120.1 MB context. With the
new `.dockerignore` it reports:

```text
Sending build context to Docker daemon  274.4kB
```

That is a reduction of roughly 438 times, and 274.4 kB is consistent with the source and
configuration files alone. `node_modules`, `dist`, and the cache files cannot be in the context.

**Evidence B, the container type checks for real.** A probe file containing a deliberate type error
was added under `src/`, which `tsconfig.json` includes:

```ts
export const disc2Poison: number = 'this is deliberately not a number'
```

The Docker build then failed exactly as a genuine type check requires:

```text
src/__disc2_poison.ts(4,14): error TS2322: Type 'string' is not assignable to type 'number'.
The command '/bin/sh -c npm run build' returned a non-zero code: 2
docker_poison_exit=2
```

The probe file was deleted immediately and its absence confirmed. Evidence A shows the
incremental cache is not present in the image; Evidence B shows the image would fail if the code
were broken. Together they rule out the masking mechanism that produced the original false green.

## GitHub Actions per-job result

Run for the fix commit `92abf32`:

| Field | Value |
|---|---|
| Run ID | `35694501920` |
| Head SHA | `92abf32e4b7d3e1d231331283d97fdf1c08673d6` |
| Event | `push` |
| Created | 2026-09-22T06:21:59Z |
| Status | completed |
| Conclusion | **success** |
| URL | https://github.com/ten10do/industrial-ai-control-tower/actions/runs/35694501920 |

| Job | Conclusion | Failed steps |
|---|---|---|
| `docs` | **success** | none |
| `backend` | **success** | none |
| `simulator` | **success** | none |
| `ml` | **success** | none |
| `frontend` | **success** | none |

### Whole workflow conclusion

**success.** All five jobs passed. This is the first green run since Phase 4, and it closes both
DISC-1 and DISC-2.

Historical context, all read from the same public API:

| Run | Head SHA | `docs` | `frontend` | Whole run |
|---|---|---|---|---|
| 35678421771 | `cff4f3cc` | failure | failure | failure |
| 35683381316 | `37f7c32f` | failure | failure | failure |
| 35685115313 | `a12cd642` | failure | failure | failure |
| 35692016246 | `2f420e1f` | success | failure | failure |
| 35692397114 | `af0bbd0` | success | failure | failure |
| **35694501920** | **`92abf32`** | **success** | **success** | **success** |

`gh` is not authenticated in this environment, so results were read from the unauthenticated public
REST API. Job log endpoints require authentication and returned 403, which is why failure causes
were reproduced locally instead.

## Regression

| Area | Command | Result |
|---|---|---|
| Frontend cold install | `npm ci` | PASS (268 packages, 0 vulnerabilities) |
| Frontend type check (forced) | `npx tsc -b --force` | PASS |
| Frontend lint | `npm run lint` | PASS |
| Frontend tests | `npm test` | 17 passed (6 files) |
| Frontend build | `npm run build` | PASS |
| Frontend Docker no-cache build | `docker build --no-cache frontend` | PASS |
| Backend tests | `pytest` (with scratch DB) | 97 passed |
| Backend lint | `ruff check .` | PASS |
| Backend types | `mypy app tests` | PASS (82 files) |

The Phase 6.6 backend regression is unaffected, as expected for a frontend-only configuration
change, and was re-run to confirm rather than assumed.

Phase 5.2 Blind Set was not re-run, as instructed.

## Environment notes

Two facts worth recording, because both will recur.

**`npm ci` cannot delete `node_modules` in this environment.** The first attempt aborted:

```text
npm error [safe-delete] 操作失败: ERROR ...node_modules\@asamuzakjp: Error during a `trash` operation
```

The sandbox shim intercepts the recursive deletion that `npm ci` performs before reinstalling, and
left `node_modules` partially destroyed (30 entries, `.bin` empty, `react` and
`@vitejs/plugin-react` missing). Following the existing convention of quarantining rather than
deleting, the damaged tree was moved out of the repository:

```text
mv frontend/node_modules D:/iac-quarantine/node_modules-broken-20260922-141447
```

`npm ci` then completed cleanly. The quarantine directory is roughly 125 MB and sits outside the
repository at `D:\iac-quarantine\`. It is no longer needed and can be removed at your discretion;
it could not be deleted here because the same shim blocks recursive deletion.

**A masked exit code nearly produced a false PASS.** The first cold-build attempt piped `npm ci`
into `tail`, so the pipeline's status was `tail`'s and a hard failure reported as `STEP1_PASS`. All
subsequent steps ran under `set -e -o pipefail`. No result in this report depends on a piped exit
code.

## Git

| Item | Value |
|---|---|
| Branch | `main` |
| Base HEAD at task start | `6a9c8ef38f321c1e4280ac185f28db508e85c6dd` |
| Fix commit | `92abf32e4b7d3e1d231331283d97fdf1c08673d6`, subject `fix: restore frontend build reliability` |
| Commit content | 2 files, 34 insertions, 1 deletion |
| Amend of pushed history | none |
| Working tree | clean, `git status --short` empty |
| Push | performed |
| `local main == origin/main` | YES |

Remote synchronization verified authoritatively against GitHub, then locally:

```text
$ git ls-remote origin refs/heads/main
92abf32e4b7d3e1d231331283d97fdf1c08673d6	refs/heads/main

$ git rev-parse HEAD origin/main
92abf32e4b7d3e1d231331283d97fdf1c08673d6
92abf32e4b7d3e1d231331283d97fdf1c08673d6

$ git status -sb
## main...origin/main
```

This report was added as a further documentation-only commit, which advances the tip. The tip hash
is obtained with `git log -1 --format=%H`; it is not embedded here because this file is part of it.
The functional fix is `92abf32`, and the report commit touches no code.

## Scope boundary

Not started, as instructed: v1.4.0, Phase 7, Kubernetes, Deployment, Cloud Infrastructure.

Phase 7: NOT_STARTED
