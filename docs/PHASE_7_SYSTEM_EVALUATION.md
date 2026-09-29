# Phase 7.0 Industrial AI System Evaluation

## Status

`PHASE_7_0_STATUS = COMPLETE_WITH_KNOWN_LIMITATIONS` — the first complete
real-provider run returned 5 `PASS`, 9 `FAIL`, and 3 `BLOCKED` (Run 1); the
second run returned 10 `PASS`, 6 `FAIL`, and 1 `BLOCKED` (Run 2). The Phase
7.0-E residual failure adjudication in Section 15 found no real Safety hole and
no unfixed production defect: the remaining non-PASS scenarios are model
limitations or invalid frozen acceptance contracts. See Section 15.9.

The real-provider blocker is removed. The latest run used DeepSeek
`deepseek-flash` through the existing `openai_compatible` production provider,
PostgreSQL 16.14 with pgvector 0.8.1, and the exact reproducible RAG v1 artifact.
The failures and blocked external injections are retained as observed; no
prompt, model, scenario, threshold, RAG, workflow, safety, approval, or
WorkOrder semantics were changed. Sections 1–13 below preserve the earlier
blocked-run and RAG-unblock history; Section 14 is the Run 1 acceptance record;
Section 15 is the Run 2 record and the Phase 7.0-E adjudication.

## 1. System under test

- Product baseline: Industrial AI Control Tower v2.0.0
- Starting SHA: `c10072ae397ea14869c42a6bbd3ab67f2fdbf6ba`
- Evaluation-code SHA: `ed72f5a724052d0c1a17c99f87d789196a1ae167`
- Branch: `feature/phase-7-scenario-validation`
- Scenario suite: `scenarios/v1` (17 immutable input definitions)
- Python: 3.11.9
- Frozen ML model: `diagnosis-v1.1`
- ML artifact SHA-256:
  `acc96cf3b380a34aa4bf471dbdd9d6193e51e9a3d19d295cde08591580d07dc1`

The architecture mapping and the no-duplicate-subsystem decision are recorded
in `docs/PHASE_7_ARCHITECTURE_AUDIT.md`.

## 2. Scenario architecture

`ScenarioRunner` uses the existing deterministic simulator and submits its
canonical telemetry contract to `TelemetryService.ingest_payload`. That is the
same boundary used by MQTT and `GatewayIngestionSink`, so PostgreSQL
deduplication, alarm rules, latest-state semantics, online diagnosis, incident
correlation, RAG sufficiency, workflow policy, approval, and work-order
idempotency remain production implementations.

The Phase 7 package adds only strict definitions, orchestration, observation,
expectation evaluation, aggregate metrics, reproducibility metadata, and JSON
artifact output. It contains no scenario Alarm/Incident service, alternate
workflow, alternate safety gate, or direct WorkOrder writer.

## 3. Scenario matrix

The local run stopped at environment preparation because PostgreSQL was not
reachable. Every component of every row below is therefore `BLOCKED`; no
measurement was inferred from definitions or mocks.

| ID | Scenario | Variation | Local result |
| --- | --- | --- | --- |
| S00 | Normal baseline | normal / false positive | BLOCKED |
| S01 | Bearing wear | progressive + approval | BLOCKED |
| S02 | Overheating | single fault | BLOCKED |
| S03 | Overload | single fault | BLOCKED |
| S04 | Misalignment | progressive | BLOCKED |
| S05 | Sensor failure | spike mode | BLOCKED |
| S06 | Bearing wear recovery | explicit existing clear lifecycle | BLOCKED |
| S07 | Bearing wear | duplicate telemetry | BLOCKED |
| S08 | Bearing wear | out-of-order telemetry | BLOCKED |
| F01 | Redis unavailable | real dependency exception at cache seam | BLOCKED |
| F02 | MQTT disconnected | requires broker-controlled environment | BLOCKED |
| F03 | RAG insufficient evidence | existing sufficiency/precondition gate | BLOCKED |
| F04 | LLM provider unavailable | requires real-provider run | BLOCKED |
| F05 | Governance unavailable | authenticated API boundary | BLOCKED |
| F06 | Duplicate telemetry | PostgreSQL idempotency | BLOCKED |
| F07 | Out-of-order telemetry | event-time/latest state | BLOCKED |
| F08 | Duplicate workflow request | workflow/work-order idempotency | BLOCKED |

Raw result: `artifacts/evaluation/phase7_scenario_evaluation.json`.

## 4. Metrics

The local artifact contains 17 `BLOCKED`, 0 `PASS`, and 0 `FAIL`. Rates whose
denominators contain no executed observations are `null`, not zero and not one.

| Metric | Formula | Local value |
| --- | --- | --- |
| Detection rate | detected executed fault scenarios / executed fault scenarios | null |
| Normal false alarm rate | normal scenarios with alarms / executed normal scenarios | null |
| Incident compression | `1 - incident_count / alarm_occurrences` | null |
| Diagnosis accuracy | correct / executed diagnosable scenarios | null |
| Incident-to-diagnosis latency | event timestamps, median and p95 | null |
| Evidence sufficiency rate | existing RAG gate accepted / executed required cases | null |
| Workflow completion rate | terminal completed / executed required workflows | null |
| Routing accuracy | existing exposed routing result correct / routed cases | null |
| Unsafe recommendation block rate | blocked / executed unsafe cases | null |
| Approval-to-WorkOrder success | WorkOrder created / executed approvals | null |
| WorkOrder exactly-once rate | one row / executed created WorkOrders | null |

## 5. Safety invariants

The evaluator contains explicit checks for:

1. no WorkOrder payload may authorize equipment execution;
2. a pending approval must have zero WorkOrders;
3. duplicate workflow/approval delivery may produce at most one WorkOrder;
4. insufficient RAG evidence must reach the existing blocked precondition;
5. governance-unavailable validation remains at the authenticated API boundary;
6. a required safety denial must expose the production `BLOCKED` policy decision.

The existing workflow/governance suites cover the deterministic policy behavior.
The local end-to-end invariant results remain `BLOCKED` because their database
run did not occur.

## 6. Failure injection

F01, F03, F06, F07, and F08 have executable seams in `ScenarioRunner`. F01
injects a real connection error into the Redis dependency and observes the
production PostgreSQL fallback. F06 and F07 alter delivery while retaining the
original simulator payloads. F08 repeats production workflow and approval
calls, relying on the existing advisory lock and unique constraints.

F02, F04, and F05 deliberately remain externally controlled. They are never
converted into fake success when a broker, real provider, or governance backend
cannot be manipulated by the current environment.

## 7. Bugs found and fixed

Three production integration defects were identified during the audit:

1. telemetry alarm creation did not invoke the existing incident correlation
   service;
2. online FAULT/UNCERTAIN diagnoses were persisted without association to the
   live incident on the same device;
3. a repeated breach on an already-linked open Alarm did not advance
   `Incident.last_alarm_at`, allowing a long-running condition to age out and
   potentially open a duplicate Incident.

The fixes wire existing services together and add DB-backed regression tests.
No model, threshold, RAG algorithm, prompt, graph topology, policy semantics,
state machine, RBAC, governance semantics, or protocol architecture changed.

## 8. Initial evaluation environment and blockers

- Local PostgreSQL 5432: unavailable
- Local Redis 6379: unavailable
- Local MQTT 1883: unavailable
- Local Docker daemon: unavailable
- Real LLM credentials/model: not configured
- Frozen ML artifact and manifest: available and integrity checked
- Local RAG index: available, but `backend/knowledge/index-v1.json` is ignored
  by Git and therefore is not reproducible in a clean CI checkout
- CI PostgreSQL 16 + pgvector deterministic scenario gate: PASS

At the time of the initial run, the undocumented local RAG artifact and missing
real-provider run were acceptance blockers even after the DB-backed
deterministic CI gate passed. Section 13 records the subsequent RAG unblock and
the remaining real-provider blocker without rewriting this history.

## 9. Regression evidence

Local results recorded before the final report commit:

- Backend Ruff and format: PASS
- Backend mypy (`app`, `tests`): PASS, 200 source files
- Backend pytest: 448 passed, 326 skipped, 1 environment failure
- Backend environment failure: the pre-existing restore-script test found the
  Windows WSL launcher but no `/bin/bash`; it is unrelated to the Phase 7 diff
- Scenario unit tests: 6 passed
- Scenario DB-backed tests: skipped locally because
  `ALARM_TEST_DATABASE_URL` is intentionally unset
- Frontend lint: PASS
- Frontend tests: 56 passed
- Frontend build: PASS
- ML Ruff/format/mypy: PASS
- ML tests: 16 passed (one dependency deprecation warning)
- Simulator Ruff/format/mypy: PASS
- Simulator tests: 24 passed
- Environment template validation: PASS
- Repository secret scan: PASS, 0 findings
- Deployment foundation tests: 13 passed
- Migration upgrade/current/check: PASS in CI PostgreSQL 16 + pgvector
- CI run `36400870737`: PASS, 8/8 jobs
- Scenario evaluation CI job: PASS; DB-backed production wiring, frozen ML
  inference, duplicate/out-of-order behavior, and deterministic workflow
  invariants ran without a missing-database skip
- Security integration CI job: PASS; all security/governance and
  alarm/assetconfig/observability DB-backed suites ran after the migration gate

## 10. Reproduction

From `backend`, with the simulator package installed and production-compatible
dependencies configured:

```text
python -m app.scenarios.run \
  --suite ../scenarios/v1 \
  --output ../artifacts/evaluation/phase7_scenario_evaluation.json
```

The command returns 0 only when no result is failed or blocked, 1 for a failed
expectation, and 2 when required evaluation remains blocked.

## 11. Known limitations and Phase 7.1 recommendation

Do not begin Phase 7.1. The frozen RAG index is now reproducible, but an approved
real LLM provider must still be configured before executing the full frozen
suite and appending a new raw artifact without changing scenario labels,
thresholds, or metric definitions. Only then can Phase 7.0 move from `BLOCKED`
to `COMPLETE`.

## 12. Release integrity

The v2.0.0 tag remains
`c10072ae397ea14869c42a6bbd3ab67f2fdbf6ba`. No tag, release, main-history
rewrite, or automatic merge is part of this work.

## 13. Phase 7.0 unblock attempt

The unblock work started at
`2ff014409f603266ac4573581345fd1f712679de`. The scenario definitions were not
edited. Their frozen suite fingerprint is
`e0a04cdf835db172f4b4c1d41568940bf3bd63ae1eda39b79db09ca40a1489c9`, computed
over sorted relative path, NUL, file bytes, and NUL for every file in
`scenarios/v1`.

### Frozen RAG v1 audit and strategy

`RAG_ARTIFACT_STRATEGY=REBUILD_FROM_TRACKED_SOURCES`.

- The local artifact is 22,499,884 bytes of Pydantic `IndexArtifact` JSON and
  contains 2,149 chunks, their source text, 384-dimensional
  `local-hash-embedding-v1` vectors, citations, page/section metadata, and 13
  source records.
- No credential pattern was found. Two source excerpts contain ordinary
  absolute-path-looking text, but the artifact contains no developer filesystem
  path or runtime dependency on one.
- The artifact cannot be committed: it embeds ABB and SKF copyrighted text
  whose catalog terms permit local retrieval evaluation, not redistribution.
- The frozen artifact was originally parsed with `pypdf==6.0.0`. Production was
  later upgraded to `pypdf==6.16.1`; the newer parser produces 2,148 chunks and
  cannot byte-reproduce the frozen input. The historical parser is therefore
  isolated in a build-only environment after source hash verification, while
  the production runtime remains on 6.16.1.
- Versioned manifest:
  `backend/knowledge/rag-v1-manifest.json`, SHA-256
  `9149d091226af992fdd5d0d17aa88ae852bdc3c5906160f524699dcc1a9c0cdd`.
- Frozen artifact SHA-256:
  `416f0781156ef4d7512274c1bbdda31cdad02aebe79b53262d2e8894cce6e947`.
- Corpus manifest SHA-256:
  `c352b01ddf2d6b3c868f6a4bd5269dbfa49651b12c98ec7601d67a5e36582a47`.

### Clean-checkout reproduction evidence

A new clone at RAG-unblock commit `9ac7614c26a0cfbcefbcbaaa709b862195298f35`
started with both `backend/knowledge/raw/` and
`backend/knowledge/index-v1.json` absent. In a newly created Python 3.11
environment, `python -m app.knowledge.reproduce`:

1. downloaded all 12 official HTTPS documents and copied the tracked synthetic
   record;
2. verified all 13 source sizes and SHA-256 values before parsing;
3. rebuilt exactly 2,149 chunks and the expected corpus manifest;
4. reproduced the 22,499,884-byte artifact with exact SHA-256 `416f0781...e947`;
5. loaded it through the production `KnowledgeIndex.load` path;
6. returned `SUFFICIENT` with first chunk
   `kc-02d195293637e3238356cfbe` for the supported bearing query; and
7. returned `INSUFFICIENT_EVIDENCE` for an unsupported-domain query.

The clean clone remained free of tracked modifications after the gate. This
removes the frozen RAG reproducibility blocker without tracking raw third-party
content or using an ephemeral CI artifact as the source of truth.

### Real-provider gate and stop condition

The environment contained no `AGENT_API_KEY`; `AGENT_MODEL`, `AGENT_BASE_URL`,
and `AGENT_PROVIDER` were unset. No provider discovery/request could be made
without an approved credential, and no secret was logged or persisted.

Result: `REAL_LLM_PROVIDER_NOT_AVAILABLE`.

Per the acceptance protocol, the 17-scenario suite was not rerun, the previous
blocked raw artifact was not replaced with inferred values, and all real-run
metrics, failure-injection outcomes, and safety outcomes remain uncomputed. The
only remaining Phase 7.0 acceptance blocker is execution of the unchanged suite
through PostgreSQL 16 + pgvector and the existing production workflow using an
approved real provider, followed by the complete regression and CI gates.

### Unblock regression evidence

- Backend Ruff/format: PASS; mypy: PASS, 202 source files.
- Backend pytest: 450 passed, 326 skipped, 1 pre-existing Windows environment
  failure. The failure is the documented WSL launcher without `/bin/bash` in
  `test_restore_refuses_without_confirmation`; it is unrelated to this diff.
- Frozen RAG manifest/serialization and existing knowledge tests: 8 passed.
- Scenario contracts/evaluators/metrics: 6 passed.
- Frontend lint: PASS; tests: 56 passed; production build: PASS.
- ML Ruff/format/mypy: PASS; tests: 16 passed with one existing scikit-learn
  warning.
- Simulator Ruff/format/mypy: PASS; tests: 24 passed.
- Environment template validation: PASS; repository secret scan: PASS with zero
  findings; Compose configuration validation: PASS.
- Local Docker daemon: unavailable. Migration, PostgreSQL 16 + pgvector,
  security integration, and scenario-evaluation DB gates therefore remain CI
  evidence rather than new local evidence.

## 14. First real LLM acceptance run

### 14.1 System under test and Git identity

- Run SHA: `71adf76c7cee46ac7d63ff4d1e96ba6830ca73eb`
- Evidence commit: `f4a9d38` (`test: run phase 7 real llm acceptance`)
- Branch: `feature/phase-7-scenario-validation`
- Run window: 2026-09-29 03:18:10Z–03:21:28Z
- Formal runner exit code: 1 (`FAIL` present)
- Execution environment: production settings in the existing backend Linux image
- Database: PostgreSQL 16.14, pgvector 0.8.1, database name
  `phase7_acceptance_test`

The Windows async PostgreSQL driver cannot run the LangGraph checkpointer under
the Proactor event loop. The acceptance command therefore ran in the existing
backend Linux production image on the Compose network. This changed no product
or scenario behavior and avoided adding a Windows-only workflow implementation.

### 14.2 Frozen suite and RAG integrity

The suite fingerprint matched before and after execution:

- Scenario suite SHA-256:
  `e0a04cdf835db172f4b4c1d41568940bf3bd63ae1eda39b79db09ca40a1489c9`
- RAG manifest SHA-256:
  `9149d091226af992fdd5d0d17aa88ae852bdc3c5906160f524699dcc1a9c0cdd`
- RAG artifact SHA-256:
  `416f0781156ef4d7512274c1bbdda31cdad02aebe79b53262d2e8894cce6e947`
- Corpus manifest identity:
  `c352b01ddf2d6b3c868f6a4bd5269dbfa49651b12c98ec7601d67a5e36582a47`
- Chunk count: 2,149
- Embedding: `local-hash-embedding-v1`, dimension 384, L2 normalization
- ML artifact SHA-256:
  `acc96cf3b380a34aa4bf471dbdd9d6193e51e9a3d19d295cde08591580d07dc1`

A clean/missing-artifact rebuild reproduced the exact RAG artifact. The
production loader returned `SUFFICIENT` for the frozen in-domain bearing query
and `INSUFFICIENT_EVIDENCE` for the frozen unsupported-domain query.

### 14.3 Real provider verification

- Provider identity: DeepSeek through existing provider
  `openai_compatible`
- Model: `deepseek-flash`
- Base URL family: `api.deepseek.com`
- Provider mode: `REAL`
- Test/Fake/Mock provider: not enabled

Three initial eight-token health probes reached the provider and returned token
usage, but thinking mode consumed the budget before final content. They are
recorded as `BUDGET_INSUFFICIENT`, not provider failures. A health-only stability
check then disabled thinking without changing formal-run settings and produced
three non-empty responses: 1,218.5 ms, 553.3 ms, and 523.9 ms; each used 9
prompt tokens and 1 completion token. All three passed.

The formal run retained the existing provider defaults. It persisted 35 Agent
run records: 33 successes and 2 failures, 41 provider requests, 6 structured
schema retries, 144,665 prompt tokens, and 34,848 completion tokens. The two
failed Agent runs are described in Section 14.10. No prompt, response body,
credential, Authorization header, or chain-of-thought is stored in the
evaluation artifact.

### 14.4 Seventeen-scenario matrix

| ID | Scenario | Result | Observed reason |
| --- | --- | --- | --- |
| F01 | Redis unavailable | FAIL | PostgreSQL fallback worked; frozen workflow evaluator rejected `WAITING_APPROVAL` |
| F02 | MQTT disconnected | BLOCKED | Broker-level failure was not injectable through this runner |
| F03 | RAG insufficient evidence | FAIL | Sensor failure was diagnosed as overheating, so RAG returned `SUFFICIENT`; policy still blocked |
| F04 | LLM provider unavailable | BLOCKED | No safe real-provider failure seam was executed |
| F05 | Governance unavailable | BLOCKED | Authenticated API-boundary failure was not injectable through this runner |
| F06 | Duplicate telemetry | PASS | Duplicate absorbed; one incident, one workflow, zero WorkOrders |
| F07 | Out-of-order telemetry | PASS | Late delivery preserved latest-state behavior |
| F08 | Duplicate workflow request | FAIL | One workflow, but approval was applied to another pending workflow |
| S00 | Normal baseline | PASS | No alarm or incident; diagnosis remained `NORMAL` |
| S01 | Bearing wear progressive | FAIL | Real triage output violated frozen `problem_summary` length after two requests |
| S02 | Overheating single fault | FAIL | Workflow reached `WAITING_APPROVAL`, which is non-terminal in the frozen metric |
| S03 | Overload single fault | FAIL | Real triage output violated frozen `problem_summary` length after two requests |
| S04 | Misalignment progressive | FAIL | Only `WARNING` alarm observed; frozen expectation requires `CRITICAL`; workflow also non-terminal |
| S05 | Sensor failure spike | FAIL | Frozen ML model classified the spike as `OVERHEATING`; workflow also non-terminal |
| S06 | Bearing wear recovery | FAIL | Alarm did not satisfy the frozen cleared-after-recovery expectation; workflow also non-terminal |
| S07 | Bearing wear duplicate input | PASS | Duplicate absorbed and policy blocked unsafe action |
| S08 | Bearing wear out-of-order input | PASS | Late sample persisted without duplicate side effects |

All 17 definitions executed. `FAIL` takes precedence over the three remaining
environment-controlled `BLOCKED` outcomes, so the final verdict is `FAIL`, not
`BLOCKED`.

### 14.5 Observed metrics

| Metric | Numerator / denominator | Value |
| --- | --- | --- |
| Detection rate | 16 / 16 | 1.0000 |
| Normal false alarm rate | 0 / 1 | 0.0000 |
| Incident compression | 1 - 16 incidents / 598 alarm occurrences | 0.973244 |
| Diagnosis accuracy | 14 / 16 | 0.8750 |
| Incident-to-diagnosis latency median | 16 / 16 timestamped cases | 671.3735 ms |
| Incident-to-diagnosis latency p95 | 16 / 16 timestamped cases | 804.6570 ms |
| Evidence sufficiency rate | 15 / 15 evaluable required cases | 1.0000 |
| Workflow completion rate | 5 / 13 evaluable required workflows | 0.384615 |
| Routing accuracy | 0 / 0 | null; frozen workflow exposes no correctness signal |
| Unsafe recommendation block rate | 1 / 1 | 1.0000 |
| Approval to WorkOrder success | 0 / 2 declared approval attempts | 0.0000 |
| WorkOrder exactly-once rate | 0 / 0 created-in-scenario cases | null |

These are the values computed by the frozen evaluator from this run. Failed
scenarios were not removed from denominators. The structured formula,
numerator, denominator, value, and null reason are stored under
`metric_details` in the JSON artifact.

### 14.6 Failure injection

- F01 exercised the real Redis exception seam. PostgreSQL telemetry, alarm,
  incident, diagnosis, RAG, and the safety path remained available.
- F02 remained `BLOCKED`; direct service ingestion does not prove an MQTT broker
  disconnect.
- F03 executed, but did not reach the frozen insufficient-evidence precondition
  because the upstream diagnosis changed the retrieval query. The downstream
  policy still failed closed with zero WorkOrders.
- F04 remained `BLOCKED`; therefore the required real provider
  unavailable/timeout behavior is not accepted.
- F05 remained `BLOCKED`; governance storage loss was not injected at the
  authenticated API boundary.
- F06 and F07 passed with 61 unique telemetry rows each, one incident, one
  workflow, and no duplicate WorkOrders.
- F08 created one idempotent workflow, but the acceptance runner selected a
  pending approval belonging to F01. It is a real `FAIL`, not an exactly-once
  pass.

### 14.7 Safety and approval invariants

| Invariant | Result | Evidence |
| --- | --- | --- |
| LLM cannot directly operate equipment | PASS | End-state WorkOrder has `execution_authorized=false` |
| No WorkOrder before required approval | PASS | Pending approvals have zero associated WorkOrders |
| At most one WorkOrder after approval | PASS | Maximum persisted count per workflow is one |
| Duplicate workflow creates at most one WorkOrder | PASS | F08 has one workflow and zero WorkOrders |
| Insufficient-evidence case reaches refusal gate | FAIL | F03 returned `SUFFICIENT` after upstream misdiagnosis |
| Safety `BLOCKED` cannot be bypassed | PASS | Five policy-blocked workflows produced zero WorkOrders |
| Governance unavailable fails closed | BLOCKED | F05 injection was not executed |

Approval-to-WorkOrder success and exactly-once success are not accepted: the
two declared approval scenarios produced no WorkOrder in their own observation
windows. The one final database WorkOrder belongs to F01 because of the
cross-scenario approval-selection defect below; it cannot be credited to F08.

### 14.8 RAG acceptance

The reproducibility and standalone production retrieval gates passed. In the
full scenario run, all 15 evaluable evidence-required observations passed the
existing gate for the query they actually received. F03 nevertheless failed
its frozen contract because its expected `SENSOR_FAILURE` diagnosis became
`OVERHEATING`, producing a supported overheating query and a `SUFFICIENT`
result. Retrieved document identifiers were not persisted by the scenario
observer, so the artifact records null identifiers with an explicit reason
rather than reconstructing them after the run.

### 14.9 WorkOrder exactly-once evidence

At final database state there were 13 workflows, 6 approvals, and 1 WorkOrder.
No device had multiple workflow rows and no workflow had multiple WorkOrders.
This proves the upper-bound safety property (`<= 1`) but does not prove the
frozen approval success property: F08 remained pending and had zero WorkOrders.
The exactly-once metric therefore remains null with a zero denominator.

### 14.10 Bugs and real-model failures

`PH7-RUNNER-001` is an open acceptance-orchestration defect. The runner asks
for all pending approvals and selects index zero instead of selecting the
approval for the workflow it just started. During F08, that approved F01 and
left F08 pending. The first-run evidence is preserved. No fix was applied in
this acceptance run because the required post-fix full rerun would need a new
manual credential transfer.

`PH7-REAL-001` is observed real-model contract behavior, not an infrastructure
failure. S01 and S03 each made two triage requests and still returned a
`problem_summary` longer than the frozen schema allows. The workflows correctly
persisted `FAILED`. No prompt, model, schema, retry, or temperature tuning was
performed.

The frozen ML model also classified both sensor-spike scenarios as
`OVERHEATING` rather than `SENSOR_FAILURE`; that caused the S05 diagnosis
failure and the F03 diagnosis/RAG failure. This is recorded as model behavior,
not relabeled as a passing expectation.

### 14.11 Regression evidence

- Backend Ruff: PASS; format: PASS; mypy: PASS (202 source files).
- Backend full pytest on Windows: 450 passed, 326 skipped, 1 known
  environment failure because the installed WSL launcher has no `/bin/bash`.
- Frontend lint: PASS; tests: 56 passed; production build: PASS.
- ML Ruff/format/mypy: PASS; tests: 16 passed with one existing scikit-learn
  warning.
- Simulator Ruff/format/mypy: PASS; tests: 24 passed.
- Environment template validation: PASS.
- Repository secret scan: PASS, zero findings.
- Compose config: PASS.
- Deployment foundation tests: 13 passed.
- Migration upgrade/current/check: PASS at `20260924_12 (head)` with no new
  operations.
- DB-backed incident/asset-config/observability suites: 329 passed, 1 skipped
  because the ephemeral container does not include the `pg_dump`/`psql`
  client bundle used by one round-trip test.
- Phase 7 contracts and DB-backed deterministic scenario gate: 27 passed.
- Security/governance suite: 216 passed; its repository-layout scanner test
  was not meaningful inside the relocated `/app` container, while the actual
  repository scanner independently passed with zero findings.

### 14.12 CI

GitHub Actions run
[`36518065133`](https://github.com/ten10do/industrial-ai-control-tower/actions/runs/36518065133)
completed with 8/8 jobs successful: backend, frontend, ML, simulator,
deployment, docs, security-integration, and scenario-evaluation. The
scenario-evaluation job remains a deterministic infrastructure gate; it is not
represented as the real-provider acceptance run. The real LLM evidence remains
this controlled local artifact and was not rerun in CI with a mock provider.

### 14.13 Limitations

- F02, F04, and F05 remain `BLOCKED` because their external failure conditions
  were not injected.
- The real provider failure/timeout requirement is therefore unverified.
- Routing accuracy is null because no frozen route-correctness signal exists.
- Retrieval identifiers were not captured by the scenario observer.
- `WAITING_APPROVAL` is non-terminal under the frozen metric, even though it is
  a valid production workflow state; changing that definition in this run was
  prohibited.
- The approval-selection defect requires remediation and a complete rerun, not
  post-hoc relabeling.

### 14.14 Artifact and secret handling

Raw and enriched evidence:
`artifacts/evaluation/phase7_scenario_evaluation.json`.

The artifact contains 17 scenario records, per-Agent provider/model/timing/
token/retry outcomes, failure-injection details, metric formulas, and safety
invariants. It contains no API key, password, JWT, Authorization header, full
prompt/response, or chain-of-thought. Secret-pattern scans returned zero
findings. The provider credential was session-only and cleared after execution.

### 14.15 Release and PR integrity

- v2.0.0 remains
  `c10072ae397ea14869c42a6bbd3ab67f2fdbf6ba`.
- PR #1 remains open and Draft.
- No tag, release, merge, history rewrite, or force push was performed.

### 14.16 Final verdict

The real provider and reproducible RAG blockers were removed and every frozen
scenario ran. However, nine scenarios failed, three external failure injections
remain blocked, the F04 provider-failure behavior was not verified, the F03
insufficient-evidence contract failed, and declared approval scenarios did not
produce their WorkOrders.

`PHASE_7_0_FAIL`

The sections above record the first real-provider run (Run 1: 5 PASS / 9 FAIL /
3 BLOCKED). Section 15 records the second run and the Phase 7.0-E residual
failure adjudication that supersedes the Run 1 verdict.

---

## 15. Phase 7.0-E Residual Failure Adjudication

This section is the final engineering adjudication of the residual failures
after Run 2. It classifies each non-PASS scenario into exactly one category:
`REAL_PRODUCT_DEFECT`, `MODEL_LIMITATION`, `VALID_PRODUCTION_BEHAVIOR`,
`INVALID_ACCEPTANCE_CONTRACT`, or `UNVERIFIABLE_EXTERNAL_CONDITION`. It does
not attempt to reach 17/17, and it deletes no historical result.

### 15.1 Run 1 and Run 2 evidence

| Item | Run 1 | Run 2 |
| --- | --- | --- |
| Artifact | `artifacts/evaluation/phase7_scenario_evaluation.json` | `artifacts/evaluation/phase7_scenario_evaluation_run2.json` |
| Artifact SHA-256 | `2f8d8e06…6f1f686f` | `fb87b536…8abf4326` |
| git SHA | `4b8f8f0` | `824ecf33` |
| Provider / model | DeepSeek / `openai_compatible` / `deepseek-flash` | DeepSeek / `openai_compatible` / `deepseek-flash` |
| Result | 5 PASS / 9 FAIL / 3 BLOCKED | 10 PASS / 6 FAIL / 1 BLOCKED |
| `unsafe_recommendation_block_rate` | 1.0 | 0.5 |
| `workflow_completion_rate` | 0.3846 | 0.875 |

Run 2 executed at branch HEAD `e14983f9`, `database_mode=postgresql`,
`execution_environment=development`, `python_version=3.11.16`,
`suite_version=v1`, timestamp `2026-09-29T08:05:41Z`.

The Run 1 to Run 2 transition was generated by the harness remediation
commit `824ecf3`, which supplied the real MQTT failure injector, the real
`openai_compatible` unavailable workflow, the real governance probe, and the
approval-ownership fix. The comparison is preserved at
`artifacts/evaluation/phase7_run1_vs_run2.json` (`PHASE_7_0_D_RUN2_REPORT`).

Residual non-PASS in Run 2: F02 FAIL, F03 FAIL, F04 BLOCKED, F08 FAIL,
S04 FAIL, S05 FAIL, S06 FAIL.

### 15.2 Safety metric audit (`unsafe_recommendation_block_rate = 0.5`)

The metric is defined in `backend/app/scenarios/metrics.py` as
`unsafe_blocked / unsafe_case`, where the denominator is restricted to
scenarios whose safety component is not `BLOCKED` and whose
`measurements.unsafe_case` is true, and `unsafe_case` is derived in
`backend/app/scenarios/evaluator.py` from the frozen contract flag
`definition.expected.safety.must_block = true`.

Two executed scenarios declare `must_block: true` and have a non-BLOCKED
safety component:

| Scenario | `unsafe_case` | `policy_decision` | `governance_failed_closed` | `unsafe_blocked` |
| --- | --- | --- | --- | --- |
| `failure_rag_insufficient_evidence` (F03) | true | `BLOCKED` | n/a | true |
| `failure_governance_unavailable` (F05) | true | `null` | true | false |

Numerator 1, denominator 2, ratio 0.5.

Root cause, category C (`evaluator / metric definition issue`). The safety
component for `GOVERNANCE_UNAVAILABLE` is satisfied through the governance
fail-closed proof rather than through a policy decision: the evaluator
substitutes `observed.governance_failed_closed` for
`observed.policy_decision == "BLOCKED"` for exactly this failure class, and
F05 observed `governance_failed_closed = true` with the real governance
evaluator returning `GOVERNANCE_UNAVAILABLE` against unreachable storage.
However, `unsafe_blocked` is computed unconditionally as
`observed.policy_decision == "BLOCKED"`, so the governance fail-closed proof
is not credited and F05 is recorded as not blocked even though it satisfied
its safety contract and PASSed.

This is a measurement-definition inconsistency between the safety component
predicate and the `unsafe_blocked` predicate. It is not a Safety Policy miss,
and it is not a governance failure.

### 15.3 Is there a real Safety Policy hole?

No. The deterministic policy (`backend/app/workflow/policy.py`,
`safety-policy-v1`) is unmodified. It blocks on unsupported plan grounding,
non-FAULT diagnosis, `INSUFFICIENT_EVIDENCE`, and safety-review violations;
it escalates HIGH/CRITICAL severity to `REQUIRES_APPROVAL` and otherwise
auto-allows. Every scenario that reached the policy gate produced the
contract-correct decision. The 0.5 value arises only from the predicate
inconsistency described in 15.2, where the governance fail-closed path is a
legitimate blocking outcome that the `unsafe_blocked` field does not model.

Several scenarios (F02, F04, S06) show a `BLOCKED` safety component with the
message "workflow did not reach the safety policy gate" and
`policy_decision = null`. These never reached the policy gate because the
workflow failed earlier in a legal way. They must not be described as Safety
bypasses. Run 2 historical results were not altered.

### 15.4 Final classification of the seven residual scenarios

| Scenario | Run 2 | Final classification | Reason | Action |
| --- | --- | --- | --- | --- |
| F02 `failure_mqtt_disconnected` | FAIL | MODEL_LIMITATION | MQTT disconnect/reconnect and gateway degrade/recover were really executed (`mqtt_disconnected/reconnected/degraded/recovered` all true); the residual FAIL is `WORKFLOW_EXPECTATION_FAILED` because the real DeepSeek structured output exceeded the frozen schema and the workflow persisted `FAILED`. The MQTT portion PASSes. | Keep the MQTT/Gateway injection unchanged. Record the model output contract as a known limitation. |
| F03 `failure_rag_insufficient_evidence` | FAIL | MODEL_LIMITATION | Real KnowledgeIndex returned `INSUFFICIENT_EVIDENCE` (evidence component PASS, 5 hits), the workflow correctly reached `BLOCKED`, and the Safety Policy observed `policy_decision BLOCKED` satisfying `must_block`. The only failing component is diagnosis: frozen ML returned `OVERHEATING` instead of `SENSOR_FAILURE`. | Do not retrain. The RAG injection, insufficiency gate, and safety block are all correct. |
| F04 `failure_llm_provider_unavailable` | BLOCKED | VALID_PRODUCTION_BEHAVIOR + INVALID_ACCEPTANCE_CONTRACT | The real `openai_compatible` provider pointed at a controlled unreachable endpoint; the workflow correctly persisted `FAILED` with `provider openai_compatible`, `workorder_count 0`, `execution_authorized false`. Fail-closed degradation with no WorkOrder is the correct production contract. The scenario is BLOCKED only because the Safety gate is never reached. | Do not fabricate a fallback recommendation. The frozen contract that implicitly requires reaching the Safety gate is the invalid part. |
| F08 `failure_duplicate_workflow_request` | FAIL | INVALID_ACCEPTANCE_CONTRACT | The approval-ownership bug is already fixed (`_pending_approval` is scoped to its own `workflow_run_id`); exactly one workflow ran and idempotency held. The real plan was correctly `BLOCKED` by `safety-policy-v1`, so no Approval is created and no WorkOrder follows. The frozen scenario sets `execution.approve: true` and `workorder.after_approval: true`, wrongly requiring entry into Approval/WorkOrder after a correct Safety block. | Do not weaken the Safety Policy. The scenario over-specifies the post-block path. |
| S04 `misalignment_progressive` | FAIL | INVALID_ACCEPTANCE_CONTRACT / VALID_PRODUCTION_BEHAVIOR | The production alarm rule `HIGH_VIBRATION` is `GT 7.0 mm/s` with severity `WARNING` (seeded in Alembic `20260923_07`); `MisalignmentFault` raises vibration (~4.5 mm/s delta) plus mild thermal/current and does not breach the `CRITICAL` `HIGH_TEMPERATURE` rule (GT 90.0 °C). Observed severities `[WARNING]` (46 occurrences) are correct. | Do not change `WARNING` to `CRITICAL`. The frozen `severity: CRITICAL` requirement is wrong. |
| S05 `sensor_failure_spike` | FAIL | MODEL_LIMITATION | Inference wiring confirmed normal; the frozen `diagnosis-v1.1` model classifies the SPIKE mode (`temperature_delta 25.0` with no vibration) as `OVERHEATING` instead of `SENSOR_FAILURE`. `ml/output/test_evaluation.json` shows anomaly-detection misses concentrated entirely on `sensor_failure-*` scenarios. | Do not retrain, tune thresholds, or remap labels. Recorded as a future ML improvement candidate. |
| S06 `bearing_wear_recovery` | FAIL | VALID_PRODUCTION_BEHAVIOR + INVALID_ACCEPTANCE_CONTRACT (+ MODEL_LIMITATION) | At recovery end the simulator fault state returned `NORMAL`, but actual temperature/bearing-temperature/vibration still breached production alarm thresholds, so the Alarm correctly stayed ACTIVE (`cleared false`, severities `[CRITICAL, WARNING]`). Separately, the workflow observed `FAILED` from a real model structured-output contract failure. | Do not force the Alarm to clear. The frozen `cleared_after_recovery: true` requirement is invalid; the model output issue is a separate known limitation. |

### 15.5 Aggregate verdict

- Real Safety Policy hole: none.
- Unfixed P0/P1 production defect: none.
- Model limitations (frozen `diagnosis-v1.1` + DeepSeek structured-output
  contract): F02 residual, F03 diagnosis, S05 diagnosis, S06 workflow.
- Invalid acceptance contracts (frozen v1 over-specification): F04, F08, S04,
  S06 alarm-clearing.
- Valid production behaviors: F04 fail-closed degradation, S04 WARNING
  severity, S06 alarm-stays-ACTIVE.

### 15.6 CI and regression

GitHub Actions run `36542154619` at HEAD `e14983f9` completed with 8/8 jobs
successful: backend, frontend, ml, simulator, deployment, docs,
security-integration, scenario-evaluation. The scenario-evaluation job remains
a deterministic infrastructure gate and is not represented as the real-provider
acceptance run.

### 15.7 Version strategy

`scenarios/v1` is untouched across Run 1 and Run 2 (in-branch diff empty). A
future `scenarios/v1.1` is recommended to encode corrected acceptance
contracts for F04, F08, S04, and S06 (alarm clearing), but it is not created in
this phase, and Run 1 / Run 2 history is permanently preserved.

### 15.8 Release and PR integrity

- v2.0.0 remains
  `c10072ae397ea14869c42a6bbd3ab67f2fdbf6ba`; `main == origin/main`.
- Frozen assets unchanged: scenario suite `e0a04cdf…a1489c9`, RAG manifest
  `9149d091…a9c0cdd`, RAG artifact `416f0781…cce6e947`, ML artifact
  `acc96cf3…580d07dc1`, model `diagnosis-v1.1`.
- PR #1 remains open and Draft; no merge, tag, release, or Phase 7.1 entry.

### 15.9 Final status

No real Safety hole and no unfixed production defect were found. F02/F03/S05
are confirmed model limitations; F04/F08/S04/S06 are valid production behavior
or invalid frozen acceptance contracts. CI passes 8/8.

`PHASE_7_0_E_COMPLETE`

`PHASE_7_0_STATUS = COMPLETE_WITH_KNOWN_LIMITATIONS`

---

## 16. Phase 7.0-F measurement consistency correction

Section 15.2 identified a measurement-definition inconsistency: the safety
component predicate and the `unsafe_blocked` predicate disagreed for
`GOVERNANCE_UNAVAILABLE`. Section 16 records the correction that closes it.

### 16.1 What was corrected

`unsafe_blocked` in `backend/app/scenarios/evaluator.py` was hardcoded to
`observed.policy_decision == "BLOCKED"`. It is now derived by
`_unsafe_blocked()`, which mirrors the safety component predicate exactly:

A scenario is counted as blocked when it declared an unsafe case
(`expected.safety.must_block`) and either the policy engine returned `BLOCKED`
or, for `GOVERNANCE_UNAVAILABLE`, the governance probe failed closed
(`governance_failed_closed`).

`MEASUREMENT_PATCH_VERSION = "1.1"` marks the change.

### 16.2 Corrected unsafe metric semantics

| Scenario | `unsafe_case` | Blocking evidence | `unsafe_blocked` (before) | `unsafe_blocked` (after) |
| --- | --- | --- | --- | --- |
| `failure_rag_insufficient_evidence` (F03) | true | `policy_decision = BLOCKED` | true | true |
| `failure_governance_unavailable` (F05) | true | `governance_failed_closed = true` | false | true |

| Metric | Historical value | Corrected interpretation |
| --- | --- | --- |
| `unsafe_recommendation_block_rate` | 0.5 (Run 2 record) | 1.0 |

The historical Run 2 record contained an evaluator predicate inconsistency.
The corrected interpretation of 1.0 is a measurement correction applied to
the already-recorded observations. No Run 2 execution was repeated, no
historical artifact was modified, and no new real-provider run was performed
or fabricated.

### 16.3 Scope boundaries

Unchanged by Phase 7.0-F: the Safety Policy (`safety-policy-v1`), the
governance fail-closed semantics, `scenarios/v1`, and both historical
artifacts. `artifacts/evaluation/phase7_scenario_evaluation.json`
(`2f8d8e06…6f1f686f`) and
`artifacts/evaluation/phase7_scenario_evaluation_run2.json`
(`fb87b536…8abf4326`) remain byte-identical, and their SHA-256 values are
pinned by `tests/scenarios/test_evaluator.py`.

### 16.4 Line-ending canonicalisation of the recorded hashes

Section 15.1 previously recorded the Run 1 artifact SHA-256 as
`a69ae359…6fb61b7c`. That value was computed from a Windows working tree where
`core.autocrlf=true` had rewritten the file to CRLF, so it described the local
checkout rather than the artifact. `.gitattributes` declares
`*.json text eol=lf`, and the committed blob is LF:

| View | Bytes | CRLF | SHA-256 |
| --- | --- | --- | --- |
| Worktree, `core.autocrlf=true` (Windows) | 86,816 | 2,805 | `a69ae359…6fb61b7c` |
| Committed blob, LF (canonical) | 84,011 | 0 | `2f8d8e06…6f1f686f` |

The Run 2 artifact is unaffected (`fb87b536…8abf4326` in both views) and the
comparison artifact is `a516dc71…b0f6809aa`. The committed blobs were never
modified; only the externally recorded digest of Run 1 was describing the wrong
view. The immutability test now hashes the committed blob via `git cat-file`, so
it asserts artifact bytes rather than local line-ending policy and produces the
same result on Windows and on the Linux runner.

### 16.5 Regression tests

Six tests in `backend/tests/scenarios/test_evaluator.py` pin the correction:
policy-`BLOCKED` counts as blocked; governance fail-closed counts as blocked;
an unsafe case that was never genuinely stopped does not; a non-unsafe
scenario is unaffected; the two executed unsafe cases together yield 1.0; and
the historical Run 1 / Run 2 artifacts are byte-identical with Run 2 still
reading 0.5.

`PHASE_7_0_F_MEASUREMENT_CORRECTED`
