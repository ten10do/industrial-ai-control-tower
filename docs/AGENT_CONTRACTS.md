# Agent Contracts

All agent outputs used as internal system protocol must be structured. Free text is acceptable for human-readable explanations, but the consuming system must not parse free text to make decisions.

## Diagnosis Agent

### Input

```json
{
  "incident_id": "string",
  "device_context": { "device_id": "string", "type": "string", "status": "string" },
  "alarms": [{ "alarm_id": "string", "rule_id": "string", "severity": "string" }],
  "telemetry_summary": { "metrics": [...], "time_range": { "start": "ISO8601", "end": "ISO8601" } }
}
```

### Output

```json
{
  "diagnosis_id": "string",
  "incident_id": "string",
  "root_cause": "string",
  "confidence": "HIGH | MEDIUM | LOW",
  "evidence_ids": ["string"],
  "recommended_actions": ["string"],
  "status": "DRAFT | INSUFFICIENT_EVIDENCE | CONFIRMED | REJECTED"
}
```

### Failure

- `INSUFFICIENT_EVIDENCE`: not enough information to form a diagnosis.
- `TIMEOUT`: diagnosis did not complete within the allotted time.
- `FAILED`: unexpected error; details logged, not exposed.

## Knowledge Agent

### Input

```json
{
  "query": "string",
  "context": { "device_type": "string", "symptoms": ["string"] },
  "required_evidence_types": ["manual", "historical_case", "specification"],
  "min_relevance": 0.7
}
```

### Output

```json
{
  "evidence": [
    {
      "evidence_id": "string",
      "source": "string",
      "content": "string",
      "citation": "string",
      "relevance_score": 0.85,
      "sufficiency": true
    }
  ],
  "sufficiency_check": {
    "sufficient": true,
    "missing_evidence": ["string"]
  }
}
```

### Evidence Contract

- Each evidence item must include a citation.
- Relevance scores must be numeric and bounded [0, 1].
- The sufficiency check must explicitly state whether evidence is adequate.

### Failure

- `INSUFFICIENT_EVIDENCE`: retrieved evidence does not meet the sufficiency gate.
- `FAILED`: retrieval system error.

## Planning Agent

### Input

```json
{
  "diagnosis_id": "string",
  "diagnosis": { "root_cause": "string", "confidence": "string" },
  "evidence": [...],
  "constraints": { "max_duration_hours": 4, "available_parts": ["string"] }
}
```

### Output

```json
{
  "plan_id": "string",
  "diagnosis_id": "string",
  "steps": [
    { "order": 1, "action": "string", "estimated_minutes": 30 }
  ],
  "required_parts": ["string"],
  "estimated_duration_minutes": 60,
  "risk_level": "LOW | MEDIUM | HIGH",
  "status": "DRAFT | REJECTED"
}
```

### Failure

- `FAILED`: unable to produce a feasible plan.
- `REJECTED`: plan violates hard constraints.

## Safety Agent

### Input

```json
{
  "plan_id": "string",
  "plan": { "steps": [...], "risk_level": "string" },
  "context": { "device_status": "string", "operational_mode": "string" }
}
```

### Output

```json
{
  "evaluation_id": "string",
  "plan_id": "string",
  "verdict": "ALLOWED | REQUIRES_APPROVAL | REJECTED",
  "policy_violations": ["string"],
  "risk_level": "LOW | MEDIUM | HIGH",
  "explanation": "string"
}
```

### Veto Semantics

- `REJECTED`: the plan violates a hard safety policy and cannot proceed.
- `REQUIRES_APPROVAL`: the plan is conditionally allowed but needs human approval.
- `ALLOWED`: the plan passes all automated safety checks.

The Safety Agent's verdict is advisory for `REQUIRES_APPROVAL` and binding for `REJECTED`.

## WorkOrder Agent

### Input

```json
{
  "plan_id": "string",
  "approval_id": "string",
  "assignee": "string"
}
```

### Output

```json
{
  "work_order_id": "string",
  "plan_id": "string",
  "approval_id": "string",
  "assignee": "string",
  "status": "DRAFT | ASSIGNED | IN_PROGRESS | COMPLETED | CANCELLED",
  "scheduled_at": "ISO8601"
}
```

### Failure

- `BLOCKED`: approval missing or invalid.
- `FAILED`: unable to create work order in target system.
