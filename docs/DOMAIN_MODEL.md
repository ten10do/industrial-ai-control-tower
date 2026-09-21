# Domain Model

## Overview

The core domain model supports the Industrial AI Control Tower closed loop:

```text
Device → Telemetry → Alarm → Incident → Diagnosis → MaintenancePlan → Approval → WorkOrder → Feedback
```

Key principle: entities are distinct and should not be conflated.

- **Alarm ≠ Incident**: an alarm is a single threshold crossing; an incident is a correlated, triaged situation.
- **Diagnosis ≠ WorkOrder**: a diagnosis is a hypothesis with evidence; a work order is an approved, executable plan.

## Entities

### Device

A physical or logical piece of industrial equipment.

| Field | Description |
|-------|-------------|
| id | Database UUID primary key (not exposed as the industrial identity) |
| device_id | Stable industrial identifier, for example `MOTOR-001` |
| name | Human-readable name |
| type | Device category (pump, motor, compressor, etc.) |
| location | Physical or logical location |
| metadata | Tags, model, manufacturer, commissioning date |
| status | Phase 2 lifecycle: `ACTIVE`, `INACTIVE`, `DECOMMISSIONED` |
| created_at | Timestamp |
| updated_at | Timestamp |

### Telemetry

A normalized time-series measurement from a device.

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| device_id | Reference to Device |
| timestamp | Measurement timestamp |
| timestamp | UTC measurement timestamp; part of the idempotency key |
| measurements | Motor temperature, bearing temperature, vibration, electrical, speed and load fields |
| operating_state | Equipment operating state |
| fault_state | Simulator fault lifecycle state; not an AI diagnosis |
| schema_version | Source contract version |
| ingested_at | UTC persistence timestamp |

### Alarm

A single rule-based or model-detected anomaly event.

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| device_id | Reference to Device |
| telemetry_id | Optional reference to triggering telemetry |
| rule_id | Rule or model that fired |
| severity | `INFO`, `WARNING`, `CRITICAL` |
| status | `ACTIVE`, `ACKNOWLEDGED`, `CLEARED` |
| started_at | Timestamp |
| cleared_at | Optional timestamp |

### Incident

A triaged situation that may involve one or more alarms and requires diagnosis.

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| title | Short description |
| description | Detailed description |
| alarm_ids | Related alarms |
| device_ids | Related devices |
| status | Phase 5: `OPEN`, `UNDER_ANALYSIS`, `ACTION_PENDING`, `WORK_ORDER_CREATED`, `CLOSED` |
| priority | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| created_at | Timestamp |
| updated_at | Timestamp |

### Diagnosis

A structured diagnostic hypothesis produced by the Diagnosis Agent.

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| incident_id | Reference to Incident |
| agent_run_id | Reference to AgentRun |
| root_cause | Proposed root cause |
| confidence | Confidence score or level |
| evidence_ids | References to Evidence |
| recommended_actions | List of recommended actions |
| status | `DRAFT`, `CONFIRMED`, `REJECTED`, `INSUFFICIENT_EVIDENCE` |

### Evidence

A piece of supporting information retrieved by the Knowledge Agent.

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| source | Document, manual, historical case |
| content | Retrieved text or summary |
| citation | Location in source |
| relevance_score | Retrieval relevance |
| sufficiency | Whether this evidence satisfies the sufficiency gate |

Phase 4 evidence additionally carries stable `document_id`, `chunk_id`, document title, page,
section, heading, source URL, revision, retrieval score, optional rerank score, and a structured
citation. It is immutable output from a versioned corpus, not an executable instruction.

### KnowledgeDocument and KnowledgeChunk

`KnowledgeDocument` records provenance, source type, license note, SHA-256, corpus version, and
page/chunk counts. `KnowledgeChunk` records stable text location, filtering metadata, content hash,
and a 384-dimensional versioned embedding. A changed source replaces only its own chunks.

### RetrievalRun

A durable audit record containing the built query, filters, retrieval/corpus/embedding versions,
candidate and selected evidence, deterministic sufficiency result, latency, and timestamp.

### MaintenancePlan

A proposed set of maintenance actions.

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| diagnosis_id | Reference to Diagnosis |
| steps | Ordered list of actions |
| workflow_run_id | Owning workflow; unique |
| version / plan_hash | Stale-approval protection |
| steps | Typed taxonomy actions with current evidence IDs |
| tools_required | Declared maintenance tools, not agent tool permissions |
| estimated_risk | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| status | Phase 5 persistence status (`READY`) |

### Approval

A human approval request and decision.

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| workflow_run_id | Owning workflow; unique |
| maintenance_plan_id | Exact plan under review |
| actor | Development identity header value |
| plan_version / plan_hash | Immutable decision target |
| decision | `PENDING`, `APPROVED`, `REJECTED` |
| decided_at | Timestamp |
| reason | Human justification |

### WorkOrder

A maintenance task record and recommendation. It is not equipment execution authorization.

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| maintenance_plan_id | Reference to MaintenancePlan |
| approval_id | Reference to Approval |
| workflow_run_id | Owning workflow; unique for exactly-once creation |
| device_id / incident_id / diagnosis_id | Full decision lineage |
| plan / evidence_refs | Frozen recommendation and citations |
| safety_requirements | Deterministic policy reasons |
| status | Phase 5 only creates `DRAFT` |

### AgentRun

A single execution of an agent or orchestrator workflow.

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| trace_id | Distributed trace identifier |
| agent_name | Name of agent or orchestrator |
| input_reference | Reference to input |
| output_reference | Reference to output |
| tool_calls | List of tool invocations |
| model | Model used |
| latency_ms | Execution time |
| status | `SUCCESS`, `FAILED`, `TIMEOUT`, `RETRYING`, `BLOCKED`, `NOT_RUN`, `INSUFFICIENT_EVIDENCE`, `REQUIRES_APPROVAL`, `REJECTED` |
| timestamp | Start time |

### WorkflowRun

The durable Phase 5 aggregate. It records the workflow/idempotency/policy versions, provider/model,
prompt versions, current typed state, stage, attempts, errors, plan version, trace, and timestamps.
The idempotency key is derived from incident, diagnosis, and workflow version.

### AuditEvent

An immutable record of a significant action or decision.

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| trace_id | Distributed trace identifier |
| run_id | Reference to AgentRun |
| actor | User, agent, or system component |
| action | Action name |
| resource | Affected resource |
| status | Outcome status |
| timestamp | Event time |

## Lifecycle Notes

- A Device continuously produces Telemetry.
- Telemetry evaluation creates Alarms.
- One or more Alarms may be grouped into an Incident.
- An Incident triggers an AgentRun of the Diagnosis Agent.
- Diagnosis may retrieve Evidence; if insufficient, the workflow stops with `INSUFFICIENT_EVIDENCE`.
- A confirmed Diagnosis feeds into a MaintenancePlan.
- The MaintenancePlan is evaluated by the Safety Agent and, if necessary, sent for Approval.
- An approved MaintenancePlan becomes a WorkOrder.
- Phase 5 stops after draft WorkOrder creation. Completion/feedback requires a future verified
  execution integration and is never inferred from an approval.
