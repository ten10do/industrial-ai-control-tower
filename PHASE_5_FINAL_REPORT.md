# PHASE_5_FINAL_REPORT

STATUS: **PARTIAL**

PHASE_5_FINAL_STATUS: **PARTIAL**

PHASE_6_READINESS: **NOT_READY**

The Phase 5 engineering workflow, deterministic safety, durable HITL, and deterministic evaluation
gates pass. The mandatory real runtime LLM gate ran but failed its workflow-success and routing
thresholds. The deterministic `TestProvider` results below are not represented as real-agent
results.

## Repository

- Repository: `D:\industrial-ai-control-tower`
- Branch: `main`
- HEAD: `0a6ed710cb7fd379f4dca480049976f99f36517a`
- Git status: dirty by design; Phase 5 implementation and documentation are uncommitted
- Preflight baseline matched the requested branch, HEAD, and clean status before implementation

## Runtime LLM

- Runtime interface: `AgentModelProvider`
- Real provider adapter: `openai_compatible`
- Base endpoint type: remote OpenAI-compatible
- Real model: `deepseek-flash`
- Real calls: 57 (Triage 24, Planning 17, Safety Review 16)
- Real successful calls: 55
- Real failed calls: 2
- Structured-output failures: 2 (`ValidationError`, terminal and not retried)
- Runtime retry count: 0
- Result: `REAL_LLM_FAILED`
- Local file identifiers `deepseek` / `DeepSeek-V4.1-Flash` were unsupported by the application and
  endpoint; the acceptance run used the existing `openai_compatible` adapter and endpoint-advertised
  `deepseek-flash` API model ID
- Test provider: `TestProvider` / `deterministic-test-provider-v1`, explicitly test-only
- Persisted deterministic integration agent calls: 19 successful, 0 failed
- WorkBuddy/development model was not used as a runtime provider

## Workflow

- Engine: LangGraph 1.2.11
- Workflow version: `maintenance-decision-workflow-v1`
- Typed state: Pydantic `WorkflowState`; checkpoints store primitive JSON-compatible values
- Checkpoint backend: PostgreSQL via `langgraph-checkpoint-postgres` 3.1.2
- Schema ownership: Alembic `20260920_04`, including visible checkpoint tables/migrations
- States: `CREATED`, `TRIAGED`, `PLAN_READY`, `SAFETY_REVIEW`, `BLOCKED`,
  `REQUIRES_APPROVAL`, `WAITING_APPROVAL`, `APPROVED`, `REJECTED`, `AUTO_ALLOWED`,
  `WORK_ORDER_CREATED`, `CANCELLED`, `FAILED`
- Terminal scope: draft recommendation/work order only; no maintenance completion or device action
- Trigger idempotency: incident + diagnosis + workflow version, unique constraint plus transaction lock
- Side effects: unique plan, approval, and work order per workflow

## Agent Versions

- Triage: `triage-prompt-v2`
- Planning: `planning-prompt-v2`
- Safety Review: `safety-review-prompt-v2`
- Outputs: provider JSON mode, complete schema in controlled prompt, strict Pydantic validation
- Temperature: configurable, default real-provider value 0.1
- Tools: read-only registry/allowlists; no runtime tool calls in Phase 5
- Injection boundary: retrieved text is explicitly delimited as untrusted evidence

## Safety

- Policy: `safety-policy-v1`
- Final authority: deterministic policy, never the Safety Review Agent
- Diagnosis preservation: fault-type overwrite and uncertain input are deterministically blocked
- Diagnosis severity authority: approval policy uses the immutable Diagnosis severity rather than
  an LLM-downgraded severity
- Grounding: every step must cite an evidence ID in the current knowledge snapshot
- Approval actions: `STOP`, `ISOLATE`, `LOCKOUT_TAGOUT`, `DISASSEMBLE`, `REPLACE`, `RESTART`
- Unsafe action auto-pass rate: **0.00%**
- Approval routing accuracy: **100.00%**
- Unsupported actionable step rate: **0.00%**

## Evaluation

- Dataset: `backend/evaluation/phase5_scenarios.csv`
- Scenario count: **80**
- Distribution: Bearing Wear 15, Overload 12, Overheating 12, Misalignment 12,
  Sensor Failure 9, Uncertain 8, Insufficient Evidence 6, Safety-critical Edge 6
- Workflow task success: **100.00%**
- Routing accuracy: **100.00%**
- Evidence grounding: **100.00%**
- Unsafe pass rate: **0.00%**
- Unnecessary approval rate: **0.00%**
- Tool precision: N/A (no runtime tool calls)
- Tool recall: N/A (no runtime tool calls)
- Limitation: this is structured semantic/policy evaluation using deterministic inputs, not a
  real-LLM quality benchmark or field-maintenance validation

## Real LLM Acceptance

- Fixed dataset: `backend/evaluation/phase5_real_llm_acceptance.csv`
- Scenario count: **24**; the set was not changed after observing model output
- Workflow success: **91.67%**
- Routing accuracy: **75.00%** (target >= 95%, FAIL)
- Evidence grounding: **100.00%**
- Unsupported actionable step rate: **0.00%**
- Unsafe action auto-pass rate: **0.00%**
- Unsafe scenarios: 22; auto-passed 0; approval required 15; blocked 7; failed 2
- Diagnosis preservation: PASS
- Insufficient evidence: both blocked before Planning, no plan
- Uncertain diagnosis: both blocked, no deterministic replacement instruction
- Prompt injection: neither case auto-approved, acquired tools, or executed device actions
- Provider failure probe: 3 bounded attempts -> `ConnectTimeout` -> terminal failure; no fabricated
  plan
- Token usage: 51,169 input / 43,241 output
- Triage latency p50/p95: 3,972.167 / 6,587.350 ms
- Planning latency p50/p95: 4,276.120 / 5,362.319 ms
- Safety latency p50/p95: 6,031.253 / 7,642.212 ms
- Cost: not estimated; no repository price table exists
- Result: `REAL_LLM_FAILED`; the run was not resampled to manufacture a pass

## HITL

- Approve test: PASS; actor/reason/version/hash persisted and draft work order created
- Reject test: PASS; repeated rejection remained `REJECTED`, zero work orders
- Stale approval test: PASS; changed plan version returned `STALE_APPROVAL`
- Concurrency test: PASS; concurrent approve/reject produced one 200 terminal decision, one 409,
  and exactly one work order
- Duplicate workflow trigger: PASS; two concurrent requests returned the same workflow ID and
  database counts were one workflow, one plan, one approval
- Cancellation: PASS; `WAITING_APPROVAL` became `CANCELLED`, later approval returned
  `WORKFLOW_CANCELLED`, zero work orders
- Development identity: required `X-Development-Actor`; no hard-coded administrator identity

## Restart

- Checkpoint recovery: PASS
- Verified sequence: high-risk bearing workflow -> `WAITING_APPROVAL` -> backend restart -> same
  waiting workflow/approval -> approve -> resume -> `WORK_ORDER_CREATED`
- Workflow ID: `27eab578-35e3-4a9a-b54c-28192ae67b27`
- Work-order ID: `6cdbb706-69ad-4660-b99a-b0d3a262ed31`
- Repeated approval returned the same work-order ID
- Exactly-once database result: **1** work order

## Failure and Retry Semantics

- Provider timeout: PASS; retried to configured maximum (3), then propagated
- Invalid structured output: PASS; failed on first Pydantic validation, no retry
- Knowledge insufficient: PASS; `BLOCKED`, no plan, zero work orders
- Checkpoint/PostgreSQL outage injection: PASS; propagated and failed closed
- Approval rejection, duplicate request, restart, stale approval, and concurrency: PASS
- Retry settings: max attempts, exponential backoff base, and node timeout are environment-driven
- No failure path auto-approves or fabricates a plan

## End-to-End Demos

- Demo A, high-risk Bearing Wear -> approval -> work order: PASS with deterministic test provider
- Demo B, Sensor Failure inspection -> `AUTO_ALLOWED` -> draft work order: PASS
- Demo C, unsupported/insufficient evidence -> `BLOCKED` -> no work order: PASS
- Demo D, model-level safe opinion for `RESTART` -> deterministic approval requirement: PASS
- Demo E, restart at approval -> resume -> exactly one work order: PASS

## Real E2E

| Stage | Result |
|---|---|
| Simulator | PASS |
| MQTT | PASS |
| Diagnosis v1.1 | PASS |
| Knowledge Evidence | PASS |
| LangGraph | PASS |
| Real Triage LLM | **FAIL** (acceptance routing) |
| Real Planning LLM | **FAIL** (one structured-output failure) |
| Real Safety LLM | **FAIL** (one structured-output failure) |
| Deterministic Safety | PASS |
| Human Approval | **NOT RUN with accepted real chain** |
| WorkOrder draft | **NOT RUN with accepted real chain** |
| REST | **NOT RUN with accepted real chain** |

The live Simulator -> MQTT -> Diagnosis -> Knowledge chain passed on the prior fresh isolated
stack. The real acceptance set exercised Triage, Planning, Safety, and deterministic policy but did
not meet acceptance thresholds, so the required Real LLM approval/resume/work-order REST chain was
not claimed or promoted as passed.

## Regression

- Backend: **29 passed** (including Knowledge 6 and Agent workflow 13)
- Backend Ruff/format: PASS
- Backend mypy strict: PASS (61 source files)
- ML: **16 passed**, Ruff/format/mypy PASS
- Simulator: **24 passed**, Ruff/format/mypy PASS
- Frontend: ESLint PASS, Vitest **1 passed**, production build PASS
- Phase 3 fresh live gate: PASS (470 telemetry rows, 91 diagnoses); restart warmup probe PASS
- Phase 4 Diagnosis -> Knowledge -> Evidence -> REST gate: PASS
- Alembic current: `20260920_04 (head)`
- Alembic drift check: no new upgrade operations
- Docker Compose configuration: PASS
- Fresh Phase 5 Docker image/migration/runtime health: PASS before final Phase 5.1 provider/policy
  edits
- `FINAL_DOCKER_REBUILD_NOT_RUN`: Docker Desktop process was present, but the Linux daemon remained
  unavailable after four bounded probes; no latest build, empty-DB migration, or readiness claim
- `pip check`: FAIL in the shared global Python environment because of pre-existing OpenTelemetry
  package conflicts
- `pip-audit`: FAIL; reported vulnerabilities include project dependencies such as `pypdf` and
  transitive `starlette`, plus unrelated globally installed packages
- `git diff --check`: PASS (line-ending warnings only)

## Security

- Provider credential is environment-only and stored as Pydantic `SecretStr`
- API keys, tokens, credentials, and full prompts are not logged
- Tracked-file pattern scan found no API key/private-key material
- Local `.env.txt` contains runtime configuration, is excluded by `.gitignore`, and was not printed
  or staged
- Test provider is forbidden outside `development`, `test`, or `ci`
- Phase 5 is disabled by default until a real provider is configured
- Evidence remains untrusted data; agents have no control/write tools

## Known Issues

- Real-provider acceptance failed: two structured-output failures, 91.67% workflow success, and
  75.00% routing accuracy.
- Full Real LLM E2E is therefore not accepted.
- Docker Desktop daemon was unavailable for the last exact-image rebuild, although the fresh
  Phase 5 image, migration, health, checkpoint restart, and APIs had already run successfully.
- Shared Python environment dependency integrity and audit scans are not clean.
- Development identity header is not production authentication/RBAC.
- The evaluation uses synthetic diagnosis data and a limited maintenance corpus.
- Prometheus/Grafana export is deferred; Phase 5 provides persisted audit data and a metrics API.

## Git Diff

Phase 5 adds the workflow/provider/policy/tool/service modules, REST APIs, Alembic schema evolution,
80-scenario dataset and gates, workflow tests, dependencies/configuration, and required architecture,
safety, approval, evaluation, and error-analysis documentation. Existing adjacent code was changed
only where required for lifecycle wiring, persistence, readiness, and documentation accuracy.

Phase 6: NOT_READY
