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
| id | Unique identifier |
| name | Human-readable name |
| type | Device category (pump, motor, compressor, etc.) |
| location | Physical or logical location |
| metadata | Tags, model, manufacturer, commissioning date |
| status | `ONLINE`, `OFFLINE`, `MAINTENANCE`, `DEGRADED` |
| created_at | Timestamp |
| updated_at | Timestamp |

### Telemetry

A normalized time-series measurement from a device.

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| device_id | Reference to Device |
| timestamp | Measurement timestamp |
| metric_name | e.g., temperature, vibration_x |
| value | Numeric or categorical value |
| unit | Unit of measure |
| quality | Data quality flag |

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
| status | `OPEN`, `IN_PROGRESS`, `RESOLVED`, `CLOSED` |
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

### MaintenancePlan

A proposed set of maintenance actions.

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| diagnosis_id | Reference to Diagnosis |
| steps | Ordered list of actions |
| required_parts | Spare parts or tools |
| estimated_duration | Estimated time |
| risk_level | `LOW`, `MEDIUM`, `HIGH` |
| status | `DRAFT`, `APPROVED`, `REJECTED` |

### Approval

A human approval request and decision.

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| request_type | `MAINTENANCE_PLAN`, `SAFETY_OVERRIDE`, `CONFIG_CHANGE` |
| requested_by | Agent or system component |
| approver_id | Human approver |
| payload | Reference to plan or action |
| decision | `PENDING`, `APPROVED`, `REJECTED` |
| decision_at | Timestamp |
| justification | Free-text justification |

### WorkOrder

An approved, executable maintenance task.

| Field | Description |
|-------|-------------|
| id | Unique identifier |
| maintenance_plan_id | Reference to MaintenancePlan |
| approval_id | Reference to Approval |
| assignee | Assigned technician or team |
| scheduled_at | Scheduled time |
| status | `DRAFT`, `ASSIGNED`, `IN_PROGRESS`, `COMPLETED`, `CANCELLED` |
| result | Completion result |

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
- WorkOrder completion produces Feedback, which may enrich future Evidence.
