# Phase 7.0 Industrial AI System Evaluation

## Status

`PHASE_7_0_BLOCKED` — `REAL_LLM_PROVIDER_NOT_AVAILABLE`

The evaluation framework and deterministic gates are implemented. The frozen
RAG reproducibility blocker was removed after the initial blocked run, but the
full real-provider acceptance run has not occurred because no approved provider
credential/model is available. No blocked or mock-backed result is reported as
a system PASS.

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
