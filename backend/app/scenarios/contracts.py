"""Strict contracts for declarative scenarios and their observed results."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Reject misspelled or future fields instead of silently changing a run."""

    model_config = ConfigDict(extra="forbid")


class FaultType(StrEnum):
    BEARING_WEAR = "BEARING_WEAR"
    OVERHEATING = "OVERHEATING"
    OVERLOAD = "OVERLOAD"
    MISALIGNMENT = "MISALIGNMENT"
    SENSOR_FAILURE = "SENSOR_FAILURE"


class ScenarioKind(StrEnum):
    NORMAL = "NORMAL"
    SINGLE_FAULT = "SINGLE_FAULT"
    PROGRESSIVE_FAULT = "PROGRESSIVE_FAULT"
    RECOVERY = "RECOVERY"
    DUPLICATE_INPUT = "DUPLICATE_INPUT"
    OUT_OF_ORDER_INPUT = "OUT_OF_ORDER_INPUT"
    FAILURE_INJECTION = "FAILURE_INJECTION"


class FailureType(StrEnum):
    REDIS_UNAVAILABLE = "REDIS_UNAVAILABLE"
    MQTT_DISCONNECTED = "MQTT_DISCONNECTED"
    RAG_INSUFFICIENT_EVIDENCE = "RAG_INSUFFICIENT_EVIDENCE"
    LLM_PROVIDER_UNAVAILABLE = "LLM_PROVIDER_UNAVAILABLE"
    GOVERNANCE_UNAVAILABLE = "GOVERNANCE_UNAVAILABLE"
    DUPLICATE_TELEMETRY = "DUPLICATE_TELEMETRY"
    OUT_OF_ORDER_TELEMETRY = "OUT_OF_ORDER_TELEMETRY"
    WORKFLOW_DUPLICATE_REQUEST = "WORKFLOW_DUPLICATE_REQUEST"


class ResultStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


class ComponentStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_RUN = "NOT_RUN"


class DeviceSpec(StrictModel):
    device_id: str = Field(min_length=1, max_length=100)
    device_type: str = Field(default="MOTOR", min_length=1, max_length=50)
    seed: int = 42


class FaultSpec(StrictModel):
    type: FaultType
    severity: float = Field(default=1.0, gt=0.0, le=1.0)
    target_signal: str | None = None


class ExecutionSpec(StrictModel):
    sample_interval_seconds: float = Field(default=1.0, gt=0.0)
    warmup_seconds: int = Field(default=30, ge=0)
    fault_duration_seconds: int = Field(default=60, ge=0)
    recovery_seconds: int = Field(default=30, ge=0)
    approve: bool = False


class AlarmExpectation(StrictModel):
    required: bool
    severity: str | None = None
    max_instances: int | None = Field(default=None, ge=0)
    cleared_after_recovery: bool = False


class IncidentExpectation(StrictModel):
    required: bool
    max_count: int | None = Field(default=None, ge=0)


class DiagnosisExpectation(StrictModel):
    required: bool = True
    expected_fault: FaultType | None = None


class EvidenceExpectation(StrictModel):
    required: bool = True
    accepted_sufficiency: list[str] = Field(default_factory=lambda: ["SUFFICIENT"])


class WorkflowExpectation(StrictModel):
    required: bool = True
    expected_status: str | None = None


class SafetyExpectation(StrictModel):
    unsafe_execution_allowed: bool = False
    must_block: bool = False


class WorkOrderExpectation(StrictModel):
    after_approval: bool = True
    max_count: int = Field(default=1, ge=0, le=1)


class ScenarioExpectations(StrictModel):
    alarm: AlarmExpectation
    incident: IncidentExpectation
    diagnosis: DiagnosisExpectation
    evidence: EvidenceExpectation
    workflow: WorkflowExpectation
    safety: SafetyExpectation
    workorder: WorkOrderExpectation


class ScenarioDefinition(StrictModel):
    schema_version: str = "1"
    scenario_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,99}$")
    description: str = Field(min_length=3, max_length=500)
    kind: ScenarioKind
    device: DeviceSpec
    fault: FaultSpec | None = None
    failure: FailureType | None = None
    execution: ExecutionSpec
    expected: ScenarioExpectations

    @model_validator(mode="after")
    def validate_kind(self) -> ScenarioDefinition:
        if self.kind == ScenarioKind.NORMAL and self.fault is not None:
            raise ValueError("normal scenarios cannot define a fault")
        if self.kind not in {ScenarioKind.NORMAL, ScenarioKind.FAILURE_INJECTION}:
            if self.fault is None:
                raise ValueError("fault scenarios must define a supported fault")
            if self.execution.fault_duration_seconds <= 0:
                raise ValueError("fault_duration_seconds must be positive for a fault scenario")
        if self.kind == ScenarioKind.FAILURE_INJECTION and self.failure is None:
            raise ValueError("failure-injection scenarios must define failure")
        if self.kind != ScenarioKind.FAILURE_INJECTION and self.failure is not None:
            raise ValueError("failure is only valid for failure-injection scenarios")
        return self


class ComponentResult(StrictModel):
    status: ComponentStatus
    observed: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


class ScenarioMeasurements(StrictModel):
    is_fault_scenario: bool
    alarm_detected: bool = False
    alarm_occurrences: int = Field(default=0, ge=0)
    incident_count: int = Field(default=0, ge=0)
    diagnosable: bool = False
    diagnosis_correct: bool = False
    incident_to_diagnosis_latency_ms: float | None = Field(default=None, ge=0)
    evidence_required: bool = False
    evidence_sufficient: bool = False
    workflow_required: bool = False
    workflow_completed: bool = False
    routing_expected: bool = False
    routing_correct: bool = False
    unsafe_case: bool = False
    unsafe_blocked: bool = False
    approval_attempted: bool = False
    workorder_created: bool = False
    workorder_count: int = Field(default=0, ge=0)


class EvaluationFailure(StrictModel):
    component: str
    code: str
    message: str


class ScenarioResult(StrictModel):
    scenario_id: str
    status: ResultStatus
    started_at: datetime
    duration_ms: float = Field(ge=0)
    alarm: ComponentResult
    incident: ComponentResult
    diagnosis: ComponentResult
    evidence: ComponentResult
    workflow: ComponentResult
    safety: ComponentResult
    approval: ComponentResult
    workorder: ComponentResult
    measurements: ScenarioMeasurements
    failures: list[EvaluationFailure] = Field(default_factory=list)


class ReproducibilityMetadata(StrictModel):
    git_sha: str
    suite_version: str
    timestamp: datetime
    python_version: str
    ml_model_version: str | None
    ml_artifact_sha256: str | None
    rag_corpus_version: str | None
    rag_embedding_version: str | None
    llm_provider: str | None
    llm_model: str | None
    database_mode: str
    execution_environment: str


class EvaluationArtifact(StrictModel):
    metadata: ReproducibilityMetadata
    scenarios: list[ScenarioResult]
    metrics: dict[str, float | int | None]
