"""Typed Phase 5 workflow, agent, policy, approval, and work-order contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.incidents.contracts import (
    AlarmRead,
    AssetContextRead,
    AuditEntryRead,
    DeviceContextRead,
)


class WorkflowStatus(StrEnum):
    CREATED = "CREATED"
    TRIAGING = "TRIAGING"
    TRIAGED = "TRIAGED"
    PLANNING = "PLANNING"
    PLAN_READY = "PLAN_READY"
    SAFETY_REVIEW = "SAFETY_REVIEW"
    BLOCKED = "BLOCKED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    AUTO_ALLOWED = "AUTO_ALLOWED"
    WORK_ORDER_CREATED = "WORK_ORDER_CREATED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class PolicyDecisionType(StrEnum):
    BLOCKED = "BLOCKED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    AUTO_ALLOWED = "AUTO_ALLOWED"


class ActionType(StrEnum):
    OBSERVE = "OBSERVE"
    INSPECT = "INSPECT"
    MEASURE = "MEASURE"
    TEST = "TEST"
    ADJUST = "ADJUST"
    STOP = "STOP"
    ISOLATE = "ISOLATE"
    LOCKOUT_TAGOUT = "LOCKOUT_TAGOUT"
    DISASSEMBLE = "DISASSEMBLE"
    REPLACE = "REPLACE"
    RESTART = "RESTART"
    ESCALATE = "ESCALATE"


class RiskLevel(StrEnum):
    """Ordered deterministic risk band.

    The band vocabulary is deliberately coarse. It is a decision-support signal
    that routes review attention; it is never an authorization. ``policy.decide``
    remains the only authority over blocking, approval, and auto-pass.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskFactor(BaseModel):
    """One deterministic contributor to a ``RiskAssessment`` score.

    ``contribution`` is the factor's share of the total score, already weighted,
    so the factors sum to the score up to floating-point tolerance. ``evidence_ref``
    names the datum the factor read, so a reviewer can trace the number back to
    the state field it came from.
    """

    name: str
    weight: float
    contribution: float
    evidence_ref: str


class RiskAssessment(BaseModel):
    """Versioned deterministic risk output.

    Produced by a pure function over the already-assembled ``DecisionContext``.
    No model call, no clock, no randomness enters this object, so the same input
    yields the same bytes. ``score`` is bounded to ``[0, 1]``; ``level`` is the
    deterministic band for that score.
    """

    level: RiskLevel
    score: float = Field(ge=0.0, le=1.0)
    factors: list[RiskFactor] = Field(default_factory=list)
    policy_version: str
    rationale: list[str] = Field(default_factory=list)


class LinkedAlarmSnapshot(BaseModel):
    """One alarm linked to the current incident, reduced for prompt consumption."""

    alarm_id: UUID
    rule_id: str
    severity: str
    status: str
    occurrence_count: int
    started_at: datetime
    last_triggered_at: datetime | None = None


class HistoricalIncidentSummary(BaseModel):
    """One bounded historical incident on the same device.

    Only closed/prior incidents enter the history. The current incident is
    excluded by the builder, so this object can never describe the incident the
    workflow is already reasoning about.
    """

    incident_id: UUID
    title: str
    status: str
    severity: str | None = None
    priority: str
    created_at: datetime
    resolved_at: datetime | None = None
    closed_at: datetime | None = None


class PriorWorkOrderSummary(BaseModel):
    """One prior work order derived from the same device's workflow history."""

    work_order_id: UUID
    incident_id: UUID
    status: str
    priority: str | None = None
    approval_status: str | None = None
    created_at: datetime


class DeviceHealthSnapshot(BaseModel):
    """Deterministic device-health derivation from a fixed telemetry window.

    Every number here is computed from a bounded, explicitly limited telemetry
    window and a baseline that is either the device/asset configuration value or
    an explicit simulator fallback. ``baseline_source`` records which one was
    used, so a caller can tell real-device evidence from simulator convenience.
    """

    device_id: str
    window_size: int
    window_start: datetime | None = None
    window_end: datetime | None = None
    sample_count: int = 0
    sufficient: bool = False
    baseline_source: str = "none"
    signals: dict[str, float] = Field(default_factory=dict)
    deviation_ratios: dict[str, float] = Field(default_factory=dict)
    max_deviation_ratio: float = 0.0
    band: str = "UNKNOWN"
    notes: list[str] = Field(default_factory=list)


class DecisionContext(BaseModel):
    """Everything the deterministic layer and the agents are allowed to see.

    Assembled once, before risk assessment, from bounded queries. It carries no
    model output and no mutable business state; it is a frozen read of the
    incident's situation. The historical and telemetry sections are untrusted
    data for prompt purposes and are delimited as such when rendered.
    """

    incident_id: UUID
    device_id: str
    incident_status: str
    incident_severity: str | None = None
    incident_priority: str
    incident_created_at: datetime
    linked_alarms: list[LinkedAlarmSnapshot] = Field(default_factory=list)
    history: list[HistoricalIncidentSummary] = Field(default_factory=list)
    history_limit: int = 0
    maintenance_history: list[PriorWorkOrderSummary] = Field(default_factory=list)
    device_health: DeviceHealthSnapshot | None = None
    prior_diagnosis_id: UUID | None = None
    prior_fault_type: str | None = None
    built_by: str
    context_version: str


class DiagnosisSnapshot(BaseModel):
    id: UUID
    status: str
    fault_type: str | None
    confidence: float | None
    severity: str | None
    model_version: str | None


class SensorEvidence(BaseModel):
    signal: str
    observation: float
    normal_baseline: float
    deviation: float
    trend: str


class KnowledgeEvidence(BaseModel):
    evidence_id: str
    document_id: str
    chunk_id: str
    text: str
    source: str
    page: int | None = None
    section: str | None = None


class KnowledgeContextSnapshot(BaseModel):
    retrieval_run_id: UUID | None = None
    sufficiency: str
    evidence: list[KnowledgeEvidence] = Field(default_factory=list)


class TriageResult(BaseModel):
    problem_summary: str = Field(min_length=3, max_length=1_000)


class MaintenanceStep(BaseModel):
    action: str = Field(min_length=3, max_length=1_000)
    action_type: ActionType
    evidence_ids: list[str] = Field(min_length=1)


class MaintenancePlanOutput(BaseModel):
    objective: str = Field(min_length=3, max_length=1_000)
    steps: list[MaintenanceStep] = Field(min_length=1, max_length=5)


class SafetyReview(BaseModel):
    hazards: list[str] = Field(default_factory=list, max_length=10)
    violations: list[str] = Field(default_factory=list, max_length=10)


class PolicyDecision(BaseModel):
    decision: PolicyDecisionType
    policy_version: str
    reasons: list[str]


class ApprovalSnapshot(BaseModel):
    approval_id: UUID
    status: str
    actor: str | None = None
    reason: str | None = None
    plan_version: int
    plan_hash: str
    decided_at: datetime | None = None


class WorkflowError(BaseModel):
    stage: str
    code: str
    message: str
    retryable: bool
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkflowState(BaseModel):
    workflow_run_id: UUID
    trace_id: str
    device_id: str
    incident_id: UUID
    diagnosis_id: UUID
    diagnosis: DiagnosisSnapshot
    sensor_evidence: list[SensorEvidence]
    knowledge_context: KnowledgeContextSnapshot
    #: Phase 7.1-A. Optional and defaulted so every ``WorkflowState`` persisted
    #: by an earlier phase still validates unchanged. ``DecisionContext`` and
    #: ``RiskAssessment`` are additive: the deterministic risk layer reads them
    #: when present and degrades to no-signal when absent, so a pre-7.1 run is
    #: never retro-failed by the new schema.
    decision_context: DecisionContext | None = None
    risk_assessment: RiskAssessment | None = None
    triage_result: TriageResult | None = None
    maintenance_plan: MaintenancePlanOutput | None = None
    safety_review: SafetyReview | None = None
    policy_decision: PolicyDecision | None = None
    approval: ApprovalSnapshot | None = None
    work_order_id: UUID | None = None
    current_stage: str = WorkflowStatus.CREATED
    status: WorkflowStatus = WorkflowStatus.CREATED
    attempt_count: int = 0
    errors: list[WorkflowError] = Field(default_factory=list)
    provider: str
    model: str
    prompt_versions: dict[str, str]
    policy_version: str
    workflow_version: str
    plan_version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentInvocation(BaseModel):
    diagnosis: DiagnosisSnapshot
    sensor_evidence: list[SensorEvidence]
    knowledge_context: KnowledgeContextSnapshot
    triage_result: TriageResult | None = None
    maintenance_plan: MaintenancePlanOutput | None = None
    #: Phase 7.1-A. Defaulted so existing constructors keep working. These two
    #: are rendered as untrusted data blocks; they never enter the instruction
    #: section and never override deterministic routing or policy.
    decision_context: DecisionContext | None = None
    risk_assessment: RiskAssessment | None = None


class ProviderUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_count: int = 1
    schema_retries: int = 0


class ProviderResult(BaseModel):
    output: dict[str, Any]
    usage: ProviderUsage = Field(default_factory=ProviderUsage)


class WorkflowCreateRequest(BaseModel):
    diagnosis_id: UUID


class IncidentCreateRequest(BaseModel):
    device_id: str
    diagnosis_id: UUID
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=2_000)
    priority: str = "MEDIUM"


class ApprovalDecisionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2_000)


class WorkflowRead(BaseModel):
    workflow_run_id: UUID
    incident_id: UUID
    diagnosis_id: UUID
    device_id: str
    status: WorkflowStatus
    current_stage: str
    workflow_version: str
    policy_version: str
    provider: str
    model: str
    state: WorkflowState
    created_at: datetime
    updated_at: datetime


class WorkflowTrace(BaseModel):
    workflow: WorkflowRead
    agent_runs: list[dict[str, Any]]


class IncidentRead(BaseModel):
    incident_id: UUID
    device_id: str
    diagnosis_id: UUID
    title: str
    status: str
    priority: str


class IncidentSummaryRead(IncidentRead):
    created_at: datetime
    updated_at: datetime
    #: Nullable since Phase 6.9-B: correlated incidents exist before any
    #: diagnosis is attached, and the list endpoint no longer refuses them.
    diagnosis_id: UUID | None = None  # type: ignore[assignment]
    diagnosis_status: str | None = None
    fault_type: str | None
    severity: str | None
    workflow_run_id: UUID | None = None
    workflow_status: str | None = None
    work_order_id: UUID | None = None


class IncidentDetailRead(IncidentSummaryRead):
    description: str
    diagnosis: dict[str, Any]


class IncidentDetailContextRead(IncidentDetailRead):
    """Incident detail plus the read-only context Phase 6.9-B assembles.

    Purely additive over ``IncidentDetailRead``: existing consumers see the same
    fields and new consumers get the alarm instances, the device and asset
    nodes, and the incident-scoped audit timeline.

    Phase 6.9-C adds ``workflow``: the summary of the incident's newest
    workflow run (or ``None`` when none was started). It reuses
    ``workflow_runs`` — no new entity, no new association table.
    """

    alarms: list[AlarmRead] = Field(default_factory=list)
    device: DeviceContextRead | None = None
    asset: AssetContextRead | None = None
    audit: list[AuditEntryRead] = Field(default_factory=list)
    workflow: WorkflowSummaryRead | None = None


class WorkflowSummaryRead(BaseModel):
    workflow_run_id: UUID
    incident_id: UUID
    diagnosis_id: UUID
    device_id: str
    status: WorkflowStatus
    current_stage: str
    policy_version: str
    provider: str
    model: str
    created_at: datetime
    updated_at: datetime


#: ``IncidentDetailContextRead`` forward-references ``WorkflowSummaryRead``,
#: which is defined below it. Both are final now, so resolve the reference.
IncidentDetailContextRead.model_rebuild()


class ApprovalRead(BaseModel):
    approval_id: UUID
    workflow_run_id: UUID
    maintenance_plan_id: UUID
    status: str
    actor: str | None
    reason: str | None
    plan_version: int
    plan_hash: str
    created_at: datetime
    decided_at: datetime | None


class WorkOrderRead(BaseModel):
    work_order_id: UUID
    workflow_run_id: UUID
    device_id: str
    incident_id: UUID
    diagnosis_id: UUID
    title: str
    priority: str
    plan: dict[str, Any]
    evidence_refs: list[str]
    safety_requirements: list[str]
    approval_id: UUID | None
    status: str
    created_at: datetime
    fault_type: str | None = None
    approval_actor: str | None = None
    approval_decided_at: datetime | None = None
