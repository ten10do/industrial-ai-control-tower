# PHASE_7_ARCHITECTURE_AUDIT

## Baseline

- Audited release: `v2.0.0`
- Audited commit: `c10072ae397ea14869c42a6bbd3ab67f2fdbf6ba`
- Development branch: `feature/phase-7-scenario-validation`
- The release tag and `main` history are out of scope and must remain unchanged.

## Production path

| Stage | Existing production implementation | Phase 7 decision |
| --- | --- | --- |
| Device simulation | `simulator.simulator.engine.SimulationEngine`, `IndustrialMotor`, `FaultManager` | Reuse the deterministic, non-realtime simulator. Do not create scenario-only signal generators. |
| MQTT input | `MqttTelemetryConsumer` | Reuse its downstream boundary. MQTT availability is evaluated separately as failure injection. |
| OPC UA / Modbus input | `GatewayIngestionSink` | No new adapter. It already normalizes and calls the canonical ingestion boundary. |
| Telemetry ingestion | `TelemetryService.ingest_payload` | The runner submits simulator messages here. This retains validation, device checks, PostgreSQL deduplication, alarm rules, latest-state handling, WebSocket fan-out, and online diagnosis. |
| Alarm lifecycle | `AlarmLifecycleService` and the database partial unique index | Reuse unchanged. Alarm occurrence compression and out-of-order timestamps are measured from persisted rows. |
| Incident correlation | `IncidentCorrelationService` | Reuse unchanged. A missing call from ingestion to this existing service is a production wiring gap, not a reason to create a scenario incident service. |
| Diagnosis | `OnlineDiagnosisCoordinator` and frozen `ModelRuntime` | Reuse the integrity-checked `diagnosis-v1.1` artifact unchanged. A missing association from a new diagnosis to the live incident is a production wiring gap. |
| RAG evidence | `KnowledgeIndex.search` and its `SufficiencyAssessment` | Reuse the existing sufficiency result. Presence of text alone never counts as sufficient evidence. |
| Workflow / Agent | `WorkflowService` and the existing LangGraph | Reuse unchanged. Mock providers may exercise integration tests but cannot produce real-agent acceptance metrics. |
| Safety | `workflow.policy.decide` plus graph precondition and policy gates | Reuse semantics unchanged. Phase 7 only observes decisions and verifies invariants. |
| Human approval | `WorkflowService.decide_approval` and LangGraph interrupt/resume | Reuse unchanged. |
| Work order | `WorkflowService._create_work_order` and `uq_work_order_workflow_run` | Reuse unchanged. Exactly-once is verified from the database. |
| Governance | `security.policy_engine` and authenticated API dependencies | Reuse fail-closed behavior and existing DB-backed governance fixtures. |
| Observability | Prometheus metrics, `WorkflowTracer`, `AuditRepository` | Reuse existing timestamps, audit records, and persisted workflow state as evidence. |

## Confirmed production seams

Both pushed and polled protocols already converge on
`TelemetryService.ingest_payload`; creating another ingestion path would bypass
the system under test. The service already enforces `(device_id, timestamp)`
deduplication in PostgreSQL and uses event time for alarm state. Its latest-state
publication and online diagnosis both reject stale/out-of-order samples.

Alarm correlation exists as a deterministic, database-backed service, but no
production ingestion caller invokes it. Online diagnoses are persisted from the
same ingestion path, but the coordinator does not associate a diagnosis with the
live incident for that device. Consequently, the audited v2.0.0 components do not
yet form the claimed Alarm -> Incident -> Diagnosis workflow entry chain without
manual database association or a second incident created by the API.

Phase 7 must close those two seams by wiring existing services together. The
scenario runner must not compensate by inserting alarms, incidents, or diagnoses.
The fixes require regression tests and must preserve the existing transaction and
idempotency constraints.

## Test and environment assets to reuse

- `backend/tests/incidents/conftest.py` provisions guarded disposable PostgreSQL
  databases and creates only the production tables needed by the tests.
- The `security-integration` CI job provides PostgreSQL 16 with pgvector and
  rejects missing-database skips.
- Existing incident, platform-reliability, workflow, governance, and security
  suites already cover lifecycle guards, duplicate telemetry, latest-state
  ordering, provider retries, policy denial, approval, and workflow idempotency.
- The frozen model artifact, manifest, knowledge corpus manifest, source catalog,
  and local knowledge index are present in the audited checkout.

## New Phase 7 layer

The new `app.scenarios` package is evaluation orchestration only. It owns:

1. strict declarative scenario schemas and loading;
2. deterministic simulator execution through the canonical ingestion boundary;
3. observation of persisted production outcomes;
4. expectation and safety-invariant evaluation;
5. aggregate metric calculation;
6. reproducibility metadata and JSON artifact output.

It does not own production Alarm, Incident, Diagnosis, RAG, Workflow, Approval,
WorkOrder, Governance, or protocol behavior.

## Prohibited duplicate subsystems

Do not add a scenario alarm service, scenario incident service, fake agent
pipeline, evaluation-only workflow, alternate safety policy, alternate RAG gate,
or direct work-order writer. Tests may use the existing `TestProvider`, clearly
labelled `MOCK_PROVIDER`, but its results are not real-provider acceptance.

## Environment finding

At audit time the local host had no reachable PostgreSQL, Redis, MQTT broker, or
Docker daemon, and no real agent-provider credentials were configured. Local
unit validation can proceed. DB-backed validation must run in the existing CI
PostgreSQL infrastructure. Real LLM metrics must remain `BLOCKED` / `NOT_RUN`
until an explicitly configured real-provider run is available.
