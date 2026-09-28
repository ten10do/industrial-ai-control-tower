# Phase 7.0 Industrial AI System Evaluation

## Status

`PHASE_7_0_BLOCKED`

The evaluation framework and deterministic gates are implemented, but the full
acceptance run has not occurred. No blocked or mock-backed result is reported as
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

## 8. Evaluation environment and blockers

- Local PostgreSQL 5432: unavailable
- Local Redis 6379: unavailable
- Local MQTT 1883: unavailable
- Local Docker daemon: unavailable
- Real LLM credentials/model: not configured
- Frozen ML artifact and manifest: available and integrity checked
- Local RAG index: available, but `backend/knowledge/index-v1.json` is ignored
  by Git and therefore is not reproducible in a clean CI checkout
- CI PostgreSQL 16 + pgvector gate: implemented, awaiting remote execution

The missing tracked RAG artifact and missing real-provider run are acceptance
blockers even after the DB-backed deterministic CI gate passes.

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
- Migration upgrade/current/check: NOT RUN (PostgreSQL unavailable)
- CI: PENDING until the feature branch is pushed and evaluated remotely

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

Do not begin Phase 7.1. First make the frozen RAG index reproducibly available
to a clean evaluation environment, run the PostgreSQL scenario gate, configure
an approved real LLM provider, execute the full frozen suite, and append the
resulting raw artifact without changing scenario labels, thresholds, or metric
definitions. Only then can Phase 7.0 move from `BLOCKED` to `COMPLETE`.

## 12. Release integrity

The v2.0.0 tag remains
`c10072ae397ea14869c42a6bbd3ab67f2fdbf6ba`. No tag, release, main-history
rewrite, or automatic merge is part of this work.
