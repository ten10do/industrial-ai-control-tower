"""Typed Phase 5 workflow, agent, policy, approval, and work-order contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


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
    diagnosis_status: str
    fault_type: str | None
    severity: str | None
    workflow_run_id: UUID | None = None
    workflow_status: str | None = None
    work_order_id: UUID | None = None


class IncidentDetailRead(IncidentSummaryRead):
    description: str
    diagnosis: dict[str, Any]


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
