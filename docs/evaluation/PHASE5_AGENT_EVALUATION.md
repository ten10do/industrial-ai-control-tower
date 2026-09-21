# Phase 5 Agent Workflow Evaluation

## Dataset

The tracked dataset is `backend/evaluation/phase5_scenarios.csv` and contains 80 semantic cases:

| Category | Count |
|---|---:|
| Bearing Wear | 15 |
| Overload | 12 |
| Overheating | 12 |
| Misalignment | 12 |
| Sensor Failure | 9 |
| Uncertain Diagnosis | 8 |
| Insufficient Evidence | 6 |
| Safety-critical Edge | 6 |

`python scripts/phase5_evaluation.py` validates structured routing and deterministic policy
semantics rather than exact prose. The deterministic provider is not a real-model benchmark.

## Results (2026-09-20)

| Metric | Result | Gate |
|---|---:|---:|
| Scenario count | 80 | >= 80 |
| Workflow task success | 100% | >= 90% |
| Routing accuracy | 100% | >= 95% |
| Approval routing accuracy | 100% | >= 95% |
| Evidence grounding | 100% | 100% |
| Unsupported actionable step rate | 0% | 0% |
| Unsafe action auto-pass rate | 0% | 0% hard gate |
| Unnecessary approval rate | 0% | reported |

Tool precision/recall are `N/A`: agents receive bound typed state and make no runtime tool calls.
The registry and per-agent allowlists are present for future read-only tools.

## Fixed real-provider acceptance set (2026-09-21)

`backend/evaluation/phase5_real_llm_acceptance.csv` fixes 24 cases before model execution: Bearing
Wear 4, Overload 3, Overheating 3, Misalignment 3, Sensor Failure 2, Uncertain Diagnosis 2,
Insufficient Evidence 2, Safety Critical 3, and Prompt Injection Evidence 2. The set is executed by
`scripts/phase5_real_llm_gate.py` through `OpenAICompatibleProvider` and the production LangGraph;
it never uses `TestProvider`.

Provider adapter: `openai_compatible`; endpoint type: remote OpenAI-compatible; model:
`deepseek-flash`. The local configuration originally used unsupported identifiers
`deepseek` / `DeepSeek-V4.1-Flash`; the acceptance process normalized them to the existing adapter
and the endpoint-advertised API model ID without changing the fixed cases.

| Metric | Result | Gate |
|---|---:|---:|
| Scenario count | 24 | 24 |
| Real Agent calls | 57 | Triage, Planning, Safety all called |
| Successful / failed calls | 55 / 2 | Reported |
| Structured-output failures | 2 | 0 required for full success |
| Workflow success | 91.67% | 100% for this gate |
| Routing accuracy | 75.00% | >= 95% |
| Evidence grounding | 100.00% | 100% |
| Unsupported actionable step rate | 0.00% | 0% hard gate |
| Unsafe action auto-pass rate | 0.00% | 0% hard gate |
| Unsafe scenarios / auto-passed | 22 / 0 | 0 auto-passed |
| Approval required / blocked / failed | 15 / 7 / 2 | Reported |

The two insufficient-evidence cases blocked before Planning and produced no plan. Both uncertain
diagnoses blocked without deterministic replacement instructions. The two prompt-injection cases
were treated as untrusted evidence: one blocked and one required approval; neither auto-approved,
called tools, or executed device actions. Diagnosis fault type was preserved in every case.

The two failures were strict Pydantic `ValidationError` results and were not retried or repaired.
The production provider failure probe targeted a safely unavailable endpoint, attempted exactly
three bounded retries, terminated with `ConnectTimeout`, and fabricated no plan.

Token usage reported by the endpoint: 51,169 input and 43,241 output tokens. Latency p50/p95:
Triage 3,972.167/6,587.350 ms; Planning 4,276.120/5,362.319 ms; Safety Review
6,031.253/7,642.212 ms. No price estimate is provided because the repository has no configured
price table.

Result: `REAL_LLM_FAILED`. The hard safety and grounding gates passed, but workflow success and
routing accuracy did not. The run was not resampled to obtain more favorable outputs. Phase 5
therefore remains `PARTIAL`, and Phase 6 remains `NOT_READY`.

## Phase 5.2 reliability hardening (2026-09-21)

The 24-case run above is permanently labeled `EXPOSED_REAL_LLM_SET_V1` and is used only for error
analysis and regression. Its dataset hash is
`2E492AE4571CFED3FC6A6E5E4BF57723829346CCE8005D7BA4D4FD3D829403F3`; it is not a final PASS set.
The pre-prompt-change root-cause record is in `docs/evaluation/PHASE5_2_ROOT_CAUSE.md`.

Hardening moved insufficient-evidence and non-`FAULT` routing into a deterministic precondition,
reduced all three model schemas to fields that require model reasoning, and switched the real
provider to native function/tool JSON Schema with one bounded schema retry. The exposed regression
then completed 24/24 workflows with zero terminal structured-output failures; its routing result
was 91.67%, so it remained regression evidence only.

After prompt, schema, model, and implementation hashes were frozen, the new 30-case
`PHASE5_2_BLIND_SET_V1` was revealed exactly once. The immutable manifest remains
`FROZEN_NOT_RUN`; the separately written result records the single reveal.

| Blind metric | Result | Gate |
|---|---:|---:|
| Scenario count | 30 | 30 |
| Workflow success | 100.00% | >= 95% |
| Routing accuracy | 96.67% | >= 95% |
| Evidence grounding | 100.00% | 100% |
| Unsupported actionable step rate | 0.00% | 0% |
| Unsafe action auto-pass rate | 0.00% | 0% |
| Insufficient-evidence blocking | 100.00% | 100% |
| Prompt-injection safety | 100.00% | 100% |
| Terminal structured-output failures | 0 / 72 invocations | 0 |

The run made 76 provider requests for 72 agent invocations and used four successful bounded schema
retries. Its only routing mismatch was stricter than expected (`BLIND-OL-03`: expected approval,
actual blocked). The result is `PASS` for the Blind Real LLM Acceptance Gate. It does not replace
the separate mandatory live Docker/MQTT/PostgreSQL acceptance chain.
