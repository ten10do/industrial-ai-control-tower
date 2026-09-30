# PHASE_7_1_ARCHITECTURE_AUDIT

Advanced Decision Intelligence — read-only architecture audit.

## 0. Audit metadata

| Field | Value |
| --- | --- |
| Baseline `main` | `cbaae638affb871444d353db2e2c8c485dad49c6` |
| Branch | `feature/phase-7-1-decision-intelligence` |
| Baseline verification | `HEAD == cbaae63…`, working tree clean except untracked `PHASE_7_0_F_MERGE_READINESS_REPORT.md` |
| Audit mode | Read-only. No production code modified. No migration created. |
| Phase 7.0 history evidence | Untouched. `docs/PHASE_7_*`, `scenarios/v1/**` unmodified. |
| Deliverable | This document. STOP after completion; no coding. |

Method. Every claim below is grounded in a file that was read at the baseline commit. Where a capability is asserted to exist, the owning module is named. Where it is asserted to be absent, the absence was checked against the full module inventory of `backend/app/`.

---

## 1. What context does the current Agent already have?

The Agent stack is a LangGraph state machine (`app/workflow/graph.py`) driven by `WorkflowService` (`app/workflow/service.py`) and typed by `app/workflow/contracts.py`. The complete context injected into every agent call is `WorkflowState`, assembled once at `WorkflowService.start()`.

### 1.1 Fields the Agent actually receives

| Field | Source | Built at | Assessment |
| --- | --- | --- | --- |
| `diagnosis` (`DiagnosisSnapshot`) | `diagnoses` row | `service.py:301` | Present. Status, fault_type, confidence, severity, model_version. |
| `sensor_evidence` (`list[SensorEvidence]`) | `diagnoses.evidence` JSONB | `service.py:311` | Present. Derived by `ModelRuntime._evidence()`, 1 entry per deviating signal. |
| `knowledge_context` (`KnowledgeContextSnapshot`) | `KnowledgeIndex.search()` | `service.py:314` | Present. Top-5 chunks, sufficiency verdict, evidence ids. |
| `triage_result` | `triage` node output | `graph.py:129` | Present. Free-text `problem_summary` only. |
| `maintenance_plan` | `planning` node output | `graph.py:170` | Present. Objective + 1-5 steps, each action_type + evidence_ids. |
| `safety_review` | `safety_review` node output | `graph.py:181` | Present. hazards + violations lists. |
| `workflow_run_id`, `trace_id`, `device_id`, `incident_id`, `diagnosis_id` | identity | `service.py:295` | Present. |
| `provider`, `model`, `prompt_versions`, `policy_version`, `workflow_version`, `plan_version` | provenance | `service.py:330` | Present. |
| `current_stage`, `status`, `attempt_count`, `errors` | runtime | constant | Present. |

### 1.2 What the Agent does NOT receive

This is the decisive finding for Phase 7.1. The context is **single-device, single-incident, single-diagnosis, point-in-time**. It carries no memory of anything that happened before.

Absent from `WorkflowState` and therefore from every prompt:

- **No incident record.** Neither `incidents.title`, `description`, `priority`, `severity`, `acknowledged_by`, `created_at`, nor `last_alarm_at` reaches the Agent. Only the `incident_id` UUID is carried, and it is used solely for persistence joins and audit, never rendered into the prompt.
- **No alarm evidence.** `incident_alarms` links exist and `IncidentContextService.linked_alarms()` reads them, but the workflow never queries them. The Agent cannot see `rule_id`, `severity`, `occurrence_count`, `started_at`, or `last_triggered_at` for any alarm.
- **No historical incidents.** There is no query anywhere in the workflow path that reads prior incidents, prior diagnoses for the same device+fault, or recurrence counts.
- **No WorkOrder / maintenance history.** `WorkOrder` rows are created but never read back into any agent invocation.
- **No device health or telemetry.** `Telemetry` is ingested and the online coordinator holds a 20-sample window in memory (`OnlineDiagnosisCoordinator`), but the window is consumed by `ModelRuntime.predict()` and discarded. No telemetry summary, trend, or freshness signal reaches the workflow.
- **No asset / organizational context.** `DeviceContextRead` and `AssetContextRead` exist in `IncidentContextRead` but are unused by the workflow.
- **No risk verdict.** The policy `decide()` runs *after* planning and safety review, and produces an enum, not a scored or explained risk object surfaced to the planner.

### 1.3 Structural consequence

The prompt template (`provider.py:render_prompt`) renders exactly five blocks: SYSTEM INSTRUCTIONS, AGENT ROLE RULES, STRUCTURED DIAGNOSIS, SENSOR EVIDENCE, PRIOR STRUCTURED OUTPUTS, UNTRUSTED RETRIEVED EVIDENCE. All five derive from `AgentInvocation`, which is built by `_invocation()` from six `WorkflowState` fields. Adding any new context dimension requires extending both `WorkflowState` and `AgentInvocation` — there is no side channel.

**Answer to Q1.** The Agent holds exactly: current diagnosis, its sensor evidence, the RAG evidence snapshot, and its own prior outputs within this one run. It holds zero historical, zero cross-incident, zero device-health, and zero maintenance context.

---

## 2. How can Historical Incident data be reused from existing tables?

The data model already stores everything required. No new table is needed for the raw history.

### 2.1 Reusable sources

| Need | Existing source | Existing access path |
| --- | --- | --- |
| Prior incidents on same device | `incidents.device_id`, `status`, `severity`, `priority`, `resolved_at` | `IncidentRepository.list_instances(device_id=…)`; index `ix_incidents_device_status` |
| Prior diagnoses for same fault | `diagnoses.fault_type`, `severity`, `confidence`, `created_at` | `DiagnosisRepository.list(device_id=…)`; index `ix_diagnosis_device_created` |
| Prior incident → alarm composition | `incident_alarms` join + `alarms` | `IncidentContextService.linked_alarms()`; index `ix_incident_alarms_alarm_id` |
| Prior resolutions | `incidents.resolved_at`, `closed_at`, `workflows.policy_decision`, `work_orders` | join on `incident_id` |
| Recurrence frequency | `COUNT(*)` over `incidents` by `device_id` + `fault_type` | derivable; no index on `(device_id, severity, created_at)` today |
| Alarm repeat behaviour | `alarms.occurrence_count`, `started_at`, `last_triggered_at` | `AlarmRepository` |

### 2.2 Design judgement

Historical reuse should be **read-only derivation, computed at workflow start, and persisted into `WorkflowRun.state`** so it is immutable and auditable. This preserves Phase 7.0 evidence integrity: the historical summary is a frozen snapshot captured at `t0`, not a live view that mutates if later incidents arrive.

Two candidate strategies, stated with trade-offs:

- **Strategy A — point query at start (recommended).** At `WorkflowService.start()`, run three bounded queries: (i) last N incidents for `device_id` newest-first; (ii) last N diagnoses for `device_id` filtered by `fault_type`; (iii) linked alarms for those incidents. Derive aggregates deterministically. Persist into the state snapshot. Cost: three indexed queries, no new table. Weakness: aggregation cost grows with history depth unless bounded by `limit`.
- **Strategy B — materialized device history table.** Precompute per-device recurrence counters. Adds a table, a write path, and an invalidation problem. For the current corpus (single-digit device count, simulator-generated history) this is premature. Reject unless measured query latency demands it.

Recommendation: Strategy A in Phase 7.1-A, with an explicit `limit` (suggest 10) and a deterministic aggregate contract. Revisit Strategy B only if the Phase 7.1 test suite shows p95 query latency above the existing workflow node budget.

---

## 3. Can WorkOrder serve as maintenance history?

**Partially. It is a valid source, but it is incomplete and must not be over-claimed.**

### 3.1 What `work_orders` provides today

`WorkOrder` (`entities.py:222`) carries: `device_id`, `incident_id`, `diagnosis_id`, `title`, `priority`, `plan` (the full maintenance plan JSON), `evidence_refs`, `safety_requirements`, `status`, `created_at`, `payload`. Created in `WorkflowService._create_work_order()` with `payload={"execution_authorized": False}`.

### 3.2 What it can and cannot answer

| Historical question | Answerable from `work_orders`? | Why |
| --- | --- | --- |
| Has this device had maintenance before? | Yes | `device_id` + `created_at`. |
| What action was previously recommended? | Yes | `plan.steps[].action` / `action_type`. |
| Which decisions were approved? | Partially | `approval_id` → `approvals.decision`, `actor`, `decided_at`. |
| Was the maintenance actually executed? | **No** | `status` is created `DRAFT` and there is no completion transition or executor field. `execution_authorized=False` forever. |
| Did the previous maintenance resolve the fault? | **No** | No outcome field, no link from work order back to a later resolution. |

### 3.3 Judgement

`WorkOrder` is usable as **recommendation history**, and that is genuinely useful for Phase 7.1: repeated identical recommendations on a device are a signal that prior intervention did not resolve the root cause. It is **not** usable as **execution history** or **outcome history**, because the system has no execution and no outcome accrual path. Phase 7.1 must describe this source as "prior recommendation and approval history", and the recommendation text must not imply the work was performed.

Adding outcome accrual (a `COMPLETED` transition and a resolution linkage) is a materially larger scope than decision intelligence and belongs to a later phase. Phase 7.1 should record it as a known limitation, not silently bridge it.

---

## 4. How should Device Health be derived from existing telemetry?

**Deterministic derivation from persisted telemetry. No LLM involvement. No new telemetry column.**

### 4.1 Inputs already present

`telemetry` (entity at `entities.py:54`) stores per-sample: `temperature_c`, `bearing_temperature_c`, `vibration_mm_s`, `current_a`, `voltage_v`, `rpm`, `load_pct`, `power_kw`, `operating_state`, `fault_state`, `timestamp`. Indexed on `(device_id, timestamp)`.

The baseline constants that make deviation meaningful already exist and are authoritative in the simulator model (`simulator/simulator/models.py:IndustrialMotor`): `RATED_CURRENT_A=10.0`, `NOMINAL_VOLTAGE_V=380.0`, `SYNCHRONOUS_RPM=1500`, `RATED_POWER_KW=5.5`, `AMBIENT_TEMPERATURE_C=25.0`, `BASE_VIBRATION_MM_S=1.8`. The `FeatureExtractor` (`app/ml/features.py`) already encodes validated signal ranges and the sliding-window statistics (mean/std/min/max/median/slope/delta/range/variance).

### 4.2 Recommended derivation

Reuse the existing repository read (`TelemetryRepository.recent_window` / `.latest`) and compute a small, bounded, deterministic vector at workflow start:

1. **Freshness** — `now - max(timestamp)`. Stale telemetry is itself a health signal and must be visible to the risk step.
2. **Sample adequacy** — count in the window; whether the window satisfies `window_size`.
3. **Deviation per signal** — z-score or ratio against the baseline constant for the eight canonical signals, reusing `SIGNAL_RANGES` for bounds.
4. **Trend** — sign and magnitude of the slope term, reusing the `slope` statistic already implemented in `FeatureExtractor`.
5. **Derived ratios** — the same cross-signal features the extractor already computes (`current_per_load`, `power_per_load`, `bearing_motor_delta`, `rpm_deviation`), which are physically interpretable proxies for overload and bearing distress.
6. **Alarm pressure** — reuse `alarms` state rather than recomputing: open alarm count, max severity, total `occurrence_count` in window.

### 4.3 Constraints

- **Do not** call `ModelRuntime` a second time for health. The diagnosis already consumed the model. Device health is a separate deterministic function over raw telemetry; conflating the two would duplicate inference and blur the diagnosis contract.
- **Do not** add a `device_health` column. Derive on demand and persist the *snapshot* inside `WorkflowRun.state` so it is frozen and auditable. A stored mutable column would be a new mutable artifact with no owner.
- **Determinism is required.** Same telemetry window in, same health vector out, so Phase 7.1 tests can assert exact values. Reuse `FeatureExtractor` constants rather than re-deriving thresholds ad hoc.

---

## 5. Which fields, tables, and interfaces are genuinely missing?

Only four gaps are real. Everything else is wired-but-unused, which is a different and cheaper problem.

### 5.1 Genuinely missing (require new work)

| # | Gap | Kind | Justification |
| --- | --- | --- | --- |
| G1 | `WorkflowState` has no historical / device-health / risk fields | Contract | `contracts.py:136`. No carrier exists for new context. |
| G2 | No deterministic risk assessment component | Logic | `policy.decide()` returns a routing enum with `reasons: list[str]`. There is no scored, explained, structured risk object. |
| G3 | No historical-context query service | Interface | No module today reads prior incidents/diagnoses/work-orders for reuse. Nothing in `repositories/` aggregates across incidents. |
| G4 | No device-health derivation function | Logic | Telemetry is read into a model window and discarded; no summary is produced. |

### 5.2 Wired but unused (reuse, do not rebuild)

| Capability | Exists at | Status |
| --- | --- | --- |
| Incident context bundle | `IncidentContextService.build_context()` | Built, exposed on the detail API, never consumed by the workflow. |
| Linked alarms | `IncidentContextService.linked_alarms()` | Implemented, unused by workflow. |
| Device + asset context | `DeviceContextRead`, `AssetContextRead` | Contracted, unused by workflow. |
| Workflow readiness gate | `IncidentWorkflowGate.ensure_ready()` | Active on the API path. |
| Telemetry window read | `TelemetryRepository.recent_window()` | Used by the diagnosis coordinator, not by the workflow. |
| Alarm instance state | `alarms.occurrence_count`, `last_triggered_at` | Populated, never read into decisions. |
| Audit timeline | `IncidentContextService.audit_timeline()` | Implemented, unused by workflow. |

### 5.3 Explicitly NOT needed

- No `IncidentV2`, no `WorkOrderV2`, no parallel incident or work-order entity.
- No new telemetry table or column.
- No new approval entity. The existing `approvals` table and its `plan_hash` / `plan_version` staleness guard already model human gating correctly.
- No new policy table. `policy.py` stays the single deterministic authority.

---

## 6. Where should Decision Intelligence be inserted in the workflow?

### 6.1 Current graph

```
START → precondition_gate ─┬─(insufficient/non-FAULT)→ precondition_block → END
                           └─→ triage → planning → safety → policy ─┬─→ blocked → END
                                                                   ├─→ approval → approved → END
                                                                   │              └→ rejected → END
                                                                   └─→ auto_allowed → END
```

### 6.2 Required pipeline shape

The mandated pipeline is:

```
DecisionContext → Risk Assessment → Structured Recommendation → Safety Policy → Human Approval → WorkOrder
```

Mapping this onto the existing graph produces a precise insertion point.

| Mandated stage | Placement | Rationale |
| --- | --- | --- |
| DecisionContext | Extend `WorkflowService.start()` assembly, before `triage` | Context must be frozen before any agent runs, so every agent sees the same snapshot. Extends `WorkflowState`; no new node needed. |
| Risk Assessment | New **deterministic** node between `precondition_gate` and `triage` | Must precede planning so the plan is conditioned on risk. Must be deterministic, so a pure node, not an agent. |
| Structured Recommendation | The `planning` node, upgraded | The existing `MaintenancePlanOutput` already is the structured recommendation. Extend its schema rather than adding a parallel agent. |
| Safety Policy | Existing `safety` → `policy` nodes, unchanged | `policy.decide()` remains the final authority. Must not be bypassed or reordered. |
| Human Approval | Existing `approval` interrupt, unchanged | Reuse the LangGraph `interrupt` / `Command(resume=…)` mechanism and the `plan_hash` staleness guard. |
| WorkOrder | Existing `WorkflowService._create_work_order()`, unchanged | Reuse the `uq_work_order_workflow_run` exactly-once constraint. |

### 6.3 Recommended graph after Phase 7.1

```
START → precondition_gate ─┬─(insufficient/non-FAULT)→ precondition_block → END
                           └─→ risk_assessment (NEW, deterministic)
                                 → triage (now sees DecisionContext + RiskAssessment)
                                 → planning (now emits structured recommendation)
                                 → safety → policy ─┬─→ blocked → END
                                                    ├─→ approval → approved → END
                                                    │              └→ rejected → END
                                                    └─→ auto_allowed → END
```

### 6.4 Critical design constraints

1. **Risk Assessment is a pure deterministic node.** It reads `DecisionContext` and produces a `RiskAssessment`. It must contain no model call, so its output is reproducible and its tests assert exact values.
2. **The LLM never reorders or overrides policy.** `policy_node` continues to run after `safety` and remains the only component that yields `PolicyDecision`. The recommendation schema may *express* a risk view, but `decide()` is the authority.
3. **`safety_review` semantics are preserved verbatim.** The safety agent still only *adds* violations; it cannot weaken policy. This invariant is already documented in `docs/SAFETY_POLICY.md` and must survive.
4. **`precondition_gate` stays first.** Blocking on non-FAULT diagnosis or insufficient evidence must remain the earliest possible exit; risk assessment must not run on inputs that are already inadmissible.
5. **Backward compatibility of `WorkflowState`.** New fields must be optional with defaults so previously persisted `workflow_runs.state` rows still validate under `WorkflowState.model_validate()`. This is the same discipline `IncidentDetailContextRead` used in Phase 6.9-C.

### 6.5 Why not insert after `policy`

Inserting risk after policy would make it advisory-only and unable to condition planning, defeating the objective of more reliable recommendations. The mandated order ("Risk Assessment → Structured Recommendation") explicitly places risk before the recommendation, which confirms pre-planning insertion.

---

## 7. Is a migration required?

**A schema migration is not required. An Alembic revision is required only if one optional index is accepted.**

### 7.1 Default: no migration

- Historical reuse reads existing tables (`incidents`, `diagnoses`, `incident_alarms`, `work_orders`, `telemetry`). All exist with appropriate indexes.
- `DecisionContext` and `RiskAssessment` are **state, not tables**. They are persisted inside `WorkflowRun.state` (JSONB), which is already the workflow's immutable snapshot column.
- Adding optional fields to `WorkflowState` is a Pydantic change, not a DDL change.

### 7.2 Optional, recommended: one additive index

If Strategy A historical queries are adopted with a `(device_id, created_at DESC)` ordering, an additive index improves p95 without changing semantics:

```sql
CREATE INDEX ix_incidents_device_created ON incidents (device_id, created_at DESC);
```

An Alembic revision would set `down_revision = "20260924_12"` (current head, `phase6_13_c_governance`). This is purely additive, reversible with a plain `DROP INDEX`, and touches no existing column or constraint. **Recommendation: include it in Phase 7.1-A only if a measured query plan justifies it.** The default position for the audit is: no migration until evidence demands one.

### 7.3 Explicitly rejected migrations

- No new `decision_contexts` table. State belongs in `workflow_runs.state`.
- No `risk_assessments` table. Same reasoning.
- No `incidents` column additions. Historical derivation must not mutate the incident contract.
- No changes to `maintenance_plans`, `approvals`, or `work_orders`.

---

## 8. Recommended architecture

### 8.1 New contracts (in `app/workflow/contracts.py` or a new `app/decision/contracts.py`)

Recommended shape, stated as intent rather than final code:

```
DecisionContext
  incident: IncidentContextSnapshot        # reused from IncidentContextService
  history: HistoricalCaseSummary           # bounded, deterministic aggregates
  maintenance_history: list[PriorWorkOrderSummary]
  device_health: DeviceHealthSnapshot
  retrieval: KnowledgeContextSnapshot      # existing
  diagnosis: DiagnosisSnapshot             # existing
  sensor_evidence: list[SensorEvidence]    # existing

RiskAssessment
  level: RiskLevel                         # LOW | MEDIUM | HIGH | CRITICAL
  score: float                             # 0..1, deterministic
  factors: list[RiskFactor]                # each with name, weight, contribution, evidence_ref
  policy_version: str
  rationale: list[str]

StructuredRecommendation  (extends MaintenancePlanOutput)
  objective, steps                         # existing
  risk_acknowledgement: str                # LLM explanation, non-authoritative
  historical_basis: list[str]              # references into DecisionContext
  confidence_basis: list[str]              # references, not free claims
```

### 8.2 Component responsibilities

| Component | Type | Authority |
| --- | --- | --- |
| `DecisionContextBuilder` | Read-only, deterministic | Assembles and freezes context at workflow start. |
| `RiskAssessor` | Pure function | Produces `RiskAssessment` from `DecisionContext`. No model call. |
| `planning` agent | LLM | Produces structured recommendation grounded in evidence. Advisory. |
| `policy.decide()` | Deterministic | **Final authority** on routing. Unchanged in authority. |
| `safety_review` agent | LLM | Additive violations only. Cannot weaken policy. |
| Approval interrupt | Human | Gates all approval-required actions. |
| `_create_work_order()` | Deterministic | Exactly-once draft creation. |

### 8.3 Prohibited in Phase 7.1

- No `IncidentV2` / `WorkOrderV2` / parallel entity.
- No direct LLM control of equipment. No new action path to an actuator.
- No bypass or reordering of `Safety Policy`.
- No modification of Phase 7.0 historical evidence artifacts.
- No modification of `scenarios/v1/**`.
- Risk must remain deterministic; the LLM contributes only structured suggestion and explanation.

---

## 9. Data and schema changes

| Change | Type | Migration | Rationale |
| --- | --- | --- | --- |
| `WorkflowState` new optional fields | Pydantic contract | No | Backward-compatible with persisted state. |
| `AgentInvocation` extended | Pydantic contract | No | Carries new context to prompts. |
| `render_prompt()` new deterministic blocks | Prompt template | No | Adds guarded, labelled context sections. |
| `RiskAssessment`, `DecisionContext` types | Pydantic contract | No | State-only. |
| `DecisionContextBuilder`, `RiskAssessor` | New modules | No | Pure logic. |
| Optional `ix_incidents_device_created` | Additive index | Conditional | Only if query-plan evidence demands it. |

Prompt-injection discipline must extend to the new blocks: historical and telemetry text enters the prompt as untrusted data, wrapped in explicit delimiters exactly as `UNTRUSTED RETRIEVED EVIDENCE` is today.

---

## 10. Test strategy

Follows `docs/TESTING_STRATEGY.md` and the Phase 7 discipline: real persisted state, no fabricated metrics.

### 10.1 Layers

1. **Unit — deterministic.** `RiskAssessor` given fixed `DecisionContext` fixtures must produce exact expected `RiskAssessment`. Table-driven, no randomness, no model.
2. **Unit — historical derivation.** Aggregation functions asserted against seeded incident/diagnosis/work-order rows.
3. **Unit — device health.** Fixed telemetry windows in, exact health vectors out, mirroring the `FeatureExtractor` test approach.
4. **Contract — backward compatibility.** Persisted pre-7.1 `WorkflowState` JSON must still validate; new fields default correctly.
5. **Graph — ordering invariants.** Assert `risk_assessment` runs after `precondition_gate` and before `triage`; assert policy still runs after safety.
6. **Policy — no weakening.** Adversarial recommendation text claiming low risk must not change `policy.decide()` output.
7. **Integration (DB-backed).** Full path with real PostgreSQL: incident → risk → plan → policy → approval → work order. Exactly-once work order asserted from the database.
8. **Regression.** Existing `test_workflow.py`, `tests/incidents/**`, `tests/scenarios/**` must pass unchanged.

### 10.2 Hard gates

- Deterministic risk reproducibility: 100% exact-match across repeated runs.
- Safety invariant: unsafe-action auto-pass rate 0%, matching the Phase 7 gate.
- Grounding: unsupported actionable step rate 0%.
- No LLM-only path can set `PolicyDecisionType`.

---

## 11. Risks

| # | Risk | Severity | Mitigation |
| --- | --- | --- | --- |
| R1 | Historical context inflates the prompt and degrades grounding | Medium | Bound every aggregate; inject summaries, never raw rows. |
| R2 | LLM treats historical text as instruction (injection) | High | Delimit and label all historical/telemetry text as untrusted; existing prompt already models this. |
| R3 | Risk score becomes a de facto policy, bypassing `decide()` | High | `RiskAssessment` is advisory; `decide()` remains sole authority; add a test that adversarial risk cannot flip routing. |
| R4 | Query latency grows with history depth | Low | Bounded `limit`, indexed ordering; revisit only on measured regression. |
| R5 | Backward-incompatible `WorkflowState` breaks persisted runs | High | All new fields optional with defaults; explicit compatibility test. |
| R6 | Device health duplicates or contradicts diagnosis | Medium | Keep health as a separate deterministic function; never call the model twice; document the boundary. |
| R7 | WorkOrder over-claimed as execution history | Medium | Name it "recommendation history" explicitly; record outcome accrual as a known limitation. |
| R8 | Scope creep into a parallel entity system | High | Prohibit `*V2`; reuse `IncidentContextService`, `policy.decide()`, existing approval and work-order paths. |
| R9 | Phase 7.0 evidence or `scenarios/v1` accidentally modified | High | Treat as read-only; verify `git diff --stat` against baseline before any commit. |
| R10 | Risk weights hardcoded without justification | Medium | Version the risk policy (`RISK_POLICY_VERSION`), keep weights in one module, document each factor's basis. |

---

## 12. Phase 7.1-A implementation plan

Scope: contracts, deterministic risk, context assembly, and tests. No UI, no new entity, no migration unless R4 is empirically triggered.

| Step | Deliverable | Acceptance |
| --- | --- | --- |
| A1 | `DecisionContext`, `RiskAssessment`, `RiskFactor`, `RiskLevel`, extended recommendation contracts | Types import cleanly; all new `WorkflowState` fields optional with defaults; existing state JSON still validates. |
| A2 | `RISK_POLICY_VERSION` + `RiskAssessor` pure function with documented, versioned factor weights | Table-driven unit tests pass; exact reproducibility across runs. |
| A3 | `DecisionContextBuilder` with bounded historical queries (limit ≈ 10) reusing existing repositories | Unit tests over seeded rows; no new table; p95 within node budget. |
| A4 | `DeviceHealthSnapshot` derivation reusing `FeatureExtractor` constants and `TelemetryRepository` | Fixed-window tests produce exact vectors; freshness and adequacy fields present. |
| A5 | Graph wiring: `risk_assessment` node between `precondition_gate` and `triage`; extended `AgentInvocation` and `render_prompt()` | Ordering-invariant tests pass; prompts contain labelled untrusted historical blocks. |
| A6 | Adversarial policy tests | Adversarially low-claimed risk cannot change `policy.decide()`; unsafe auto-pass rate 0%. |
| A7 | Regression run | `test_workflow.py`, `tests/incidents/**`, `tests/scenarios/**` green; `git diff` vs baseline touches only intended files. |
| A8 | Optional indexed migration, only if measured | Separate revision `down_revision="20260924_12"`; reversible with `DROP INDEX`. |

Out of scope for 7.1-A, deferred explicitly: outcome accrual for executed maintenance, UI surfacing, cross-device correlation, any `*V2` entity.

---

## 13. Answers index

| Question | Answer | Section |
| --- | --- | --- |
| 1. Existing Agent context | Diagnosis, sensor evidence, RAG snapshot, own prior outputs. No history, no device health. | §1 |
| 2. Historical incident reuse | Reuse existing tables via bounded deterministic queries at workflow start; freeze into state. No new table. | §2 |
| 3. WorkOrder as maintenance history | Partially. Recommendation/approval history yes; execution/outcome history no. | §3 |
| 4. Device health from telemetry | Deterministic derivation from `telemetry` using existing baseline constants and extractor statistics. | §4 |
| 5. Genuinely missing | G1 state fields, G2 deterministic risk component, G3 historical query service, G4 health derivation. | §5 |
| 6. Workflow insertion point | `DecisionContext` at start; new deterministic `risk_assessment` node between `precondition_gate` and `triage`; rest unchanged. | §6 |
| 7. Migration needed | No by default. Optional additive index only on measured evidence. | §7 |

---

## 14. Status

`PHASE_7_1_ARCHITECTURE_AUDIT: COMPLETE`

Baseline `cbaae63…` verified. Branch `feature/phase-7-1-decision-intelligence` created. No production code modified. No migration created. Phase 7.0 evidence and `scenarios/v1` untouched.

**STOP.** Per instruction, coding does not begin. Phase 7.1-A requires explicit approval before implementation.
