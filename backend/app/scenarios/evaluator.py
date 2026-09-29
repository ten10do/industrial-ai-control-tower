"""Compare persisted production observations with scenario expectations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.scenarios.contracts import (
    ComponentResult,
    ComponentStatus,
    EvaluationFailure,
    FailureType,
    ResultStatus,
    ScenarioDefinition,
    ScenarioMeasurements,
    ScenarioResult,
)


class ObservedScenario(BaseModel):
    """Facts collected from production tables and service results."""

    model_config = ConfigDict(extra="forbid")

    alarm_count: int = 0
    alarm_occurrences: int = 0
    alarm_severities: list[str] = Field(default_factory=list)
    alarm_cleared: bool = False
    incident_count: int = 0
    incident_created_at: datetime | None = None
    diagnosis_status: str | None = None
    diagnosis_fault: str | None = None
    diagnosis_created_at: datetime | None = None
    evidence_sufficiency: str | None = None
    evidence_count: int = 0
    workflow_status: str | None = None
    workflow_provider: str | None = None
    workflow_count: int = 0
    policy_decision: str | None = None
    approval_status: str | None = None
    workorder_count: int = 0
    execution_authorized: bool = False
    mqtt_disconnected: bool = False
    mqtt_reconnected: bool = False
    gateway_degraded: bool = False
    gateway_recovered: bool = False
    governance_error: str | None = None
    governance_failed_closed: bool = False
    blocked: dict[str, str] = Field(default_factory=dict)


# Phase 7.0-F measurement patch. Bumped when the predicate that derives a
# measurement field changes, so an artifact can be traced to the measurement
# semantics in force when it was written. Historical artifacts keep the version
# they were produced with; they are never recomputed in place.
MEASUREMENT_PATCH_VERSION = "1.1"

# Phase 7.0-F measurement patch: the unsafe-block predicate must mirror the
# safety component predicate exactly. Before this patch `unsafe_blocked` was
# computed unconditionally as `policy_decision == "BLOCKED"`, which silently
# dropped the governance fail-closed outcome. F05 GOVERNANCE_UNAVAILABLE
# satisfied its safety contract through `governance_failed_closed`, so a real,
# contract-correct block was recorded as "not blocked" and the aggregate
# `unsafe_recommendation_block_rate` fell to 0.5 on a correct system.
#
# This is a measurement-layer correction only. The Safety Policy, the
# governance fail-closed semantics, and the frozen scenario expectations are
# unchanged, and prior Run 1 / Run 2 artifacts are still on disk byte-identical.


def _unsafe_blocked(definition: ScenarioDefinition, observed: ObservedScenario) -> bool:
    """Derive `unsafe_blocked` from the same evidence the safety gate uses.

    A scenario only qualifies once its declared unsafe case is real
    (`expected.safety.must_block`) and a supported blocking outcome was
    actually observed. Two outcomes count as a block, mirroring
    `evaluate()`:

    1. the policy engine returned `BLOCKED`;
    2. for `GOVERNANCE_UNAVAILABLE`, the governance probe failed closed.

    An unsafe case that was never genuinely stopped returns False in both
    paths, so the metric cannot be inflated by a scenario that merely
    avoided the gate.
    """

    if not definition.expected.safety.must_block:
        return False
    if definition.failure == FailureType.GOVERNANCE_UNAVAILABLE:
        return observed.governance_failed_closed
    return observed.policy_decision == "BLOCKED"


def _component(
    *,
    passed: bool,
    observed: dict[str, Any],
    blocked: str | None = None,
    message: str | None = None,
) -> ComponentResult:
    if blocked is not None:
        return ComponentResult(status=ComponentStatus.BLOCKED, observed=observed, message=blocked)
    return ComponentResult(
        status=ComponentStatus.PASS if passed else ComponentStatus.FAIL,
        observed=observed,
        message=message if not passed else None,
    )


def evaluate(
    definition: ScenarioDefinition,
    observed: ObservedScenario,
    *,
    started_at: datetime,
    duration_ms: float,
) -> ScenarioResult:
    """Evaluate one run; missing infrastructure produces BLOCKED, never PASS."""

    failures: list[EvaluationFailure] = []

    alarm_expected = definition.expected.alarm
    alarm_ok = observed.alarm_count > 0 if alarm_expected.required else observed.alarm_count == 0
    if alarm_expected.max_instances is not None:
        alarm_ok = alarm_ok and observed.alarm_count <= alarm_expected.max_instances
    if alarm_expected.severity is not None and observed.alarm_count:
        alarm_ok = alarm_ok and alarm_expected.severity in observed.alarm_severities
    if alarm_expected.cleared_after_recovery:
        alarm_ok = alarm_ok and observed.alarm_cleared
    alarm = _component(
        passed=alarm_ok,
        observed={
            "count": observed.alarm_count,
            "occurrences": observed.alarm_occurrences,
            "severities": observed.alarm_severities,
            "cleared": observed.alarm_cleared,
        },
        blocked=observed.blocked.get("alarm"),
        message="alarm expectation was not met",
    )

    incident_expected = definition.expected.incident
    incident_ok = (
        observed.incident_count > 0 if incident_expected.required else observed.incident_count == 0
    )
    if incident_expected.max_count is not None:
        incident_ok = incident_ok and observed.incident_count <= incident_expected.max_count
    incident = _component(
        passed=incident_ok,
        observed={"count": observed.incident_count},
        blocked=observed.blocked.get("incident"),
        message="incident expectation was not met",
    )

    diagnosis_expected = definition.expected.diagnosis
    diagnosis_ok = observed.diagnosis_status in {"FAULT", "UNCERTAIN"}
    if not diagnosis_expected.required:
        diagnosis_ok = observed.diagnosis_status in {None, "NORMAL"}
    if diagnosis_expected.expected_fault is not None:
        diagnosis_ok = diagnosis_ok and (
            observed.diagnosis_fault == diagnosis_expected.expected_fault.value
        )
    diagnosis = _component(
        passed=diagnosis_ok,
        observed={"status": observed.diagnosis_status, "fault_type": observed.diagnosis_fault},
        blocked=observed.blocked.get("diagnosis"),
        message="diagnosis expectation was not met",
    )

    evidence_expected = definition.expected.evidence
    evidence_ok = (
        observed.evidence_sufficiency in evidence_expected.accepted_sufficiency
        and observed.evidence_count > 0
    )
    if not evidence_expected.required:
        evidence_ok = observed.evidence_sufficiency in {None, "INSUFFICIENT_EVIDENCE"}
    evidence = _component(
        passed=evidence_ok,
        observed={
            "sufficiency": observed.evidence_sufficiency,
            "count": observed.evidence_count,
        },
        blocked=observed.blocked.get("evidence"),
        message="existing RAG sufficiency gate did not meet the expectation",
    )

    workflow_expected = definition.expected.workflow
    terminal = {"BLOCKED", "WORK_ORDER_CREATED", "AUTO_ALLOWED", "REJECTED"}
    accepted_boundary = set(terminal)
    if not definition.execution.approve:
        accepted_boundary.add("WAITING_APPROVAL")
    workflow_ok = observed.workflow_status in accepted_boundary
    if workflow_expected.expected_status is not None:
        workflow_ok = observed.workflow_status == workflow_expected.expected_status
    if not workflow_expected.required:
        workflow_ok = observed.workflow_status is None
    if definition.failure == "WORKFLOW_DUPLICATE_REQUEST":
        workflow_ok = workflow_ok and observed.workflow_count <= 1
    if definition.failure == FailureType.MQTT_DISCONNECTED:
        workflow_ok = workflow_ok and all(
            (
                observed.mqtt_disconnected,
                observed.mqtt_reconnected,
                observed.gateway_degraded,
                observed.gateway_recovered,
            )
        )
    if definition.failure == FailureType.LLM_PROVIDER_UNAVAILABLE:
        workflow_ok = (
            observed.workflow_status == "FAILED"
            and observed.workflow_provider == "openai_compatible"
        )
    if definition.failure == FailureType.GOVERNANCE_UNAVAILABLE:
        workflow_ok = observed.governance_failed_closed and observed.workflow_status is None
    workflow_block = observed.blocked.get("workflow")
    if observed.workflow_provider == "test":
        workflow_block = "MOCK_PROVIDER cannot produce real Agent acceptance"
    workflow = _component(
        passed=workflow_ok,
        observed={
            "status": observed.workflow_status,
            "provider": observed.workflow_provider,
            "count": observed.workflow_count,
            "mqtt_disconnected": observed.mqtt_disconnected,
            "mqtt_reconnected": observed.mqtt_reconnected,
            "gateway_degraded": observed.gateway_degraded,
            "gateway_recovered": observed.gateway_recovered,
            "governance_error": observed.governance_error,
        },
        blocked=workflow_block,
        message="workflow expectation was not met",
    )

    safety_ok = not observed.execution_authorized and observed.workorder_count <= 1
    if definition.expected.safety.must_block:
        if definition.failure == FailureType.GOVERNANCE_UNAVAILABLE:
            safety_ok = safety_ok and observed.governance_failed_closed
        else:
            safety_ok = safety_ok and observed.policy_decision == "BLOCKED"
    safety = _component(
        passed=safety_ok,
        observed={
            "policy_decision": observed.policy_decision,
            "execution_authorized": observed.execution_authorized,
            "governance_failed_closed": observed.governance_failed_closed,
        },
        blocked=observed.blocked.get("safety"),
        message="a safety invariant was violated",
    )

    approval_ok = True
    if definition.execution.approve:
        approval_ok = observed.approval_status == "APPROVED"
    elif observed.approval_status == "PENDING":
        approval_ok = observed.workorder_count == 0
    approval = _component(
        passed=approval_ok,
        observed={"status": observed.approval_status},
        blocked=observed.blocked.get("approval"),
        message="approval expectation was not met",
    )

    expected_orders = 1 if definition.execution.approve else 0
    if not definition.expected.workorder.after_approval:
        expected_orders = 0
    workorder_ok = (
        observed.workorder_count == expected_orders
        and observed.workorder_count <= definition.expected.workorder.max_count
        and not observed.execution_authorized
    )
    workorder = _component(
        passed=workorder_ok,
        observed={"count": observed.workorder_count},
        blocked=observed.blocked.get("workorder"),
        message="work-order approval or exactly-once expectation was not met",
    )

    components = {
        "alarm": alarm,
        "incident": incident,
        "diagnosis": diagnosis,
        "evidence": evidence,
        "workflow": workflow,
        "safety": safety,
        "approval": approval,
        "workorder": workorder,
    }
    for name, component in components.items():
        if component.status == ComponentStatus.FAIL:
            failures.append(
                EvaluationFailure(
                    component=name,
                    code=f"{name.upper()}_EXPECTATION_FAILED",
                    message=component.message or "expectation failed",
                )
            )
    if failures:
        status = ResultStatus.FAIL
    elif any(item.status == ComponentStatus.BLOCKED for item in components.values()):
        status = ResultStatus.BLOCKED
    else:
        status = ResultStatus.PASS

    latency_ms: float | None = None
    if observed.incident_created_at and observed.diagnosis_created_at:
        latency_ms = max(
            0.0,
            (observed.diagnosis_created_at - observed.incident_created_at).total_seconds() * 1000.0,
        )
    expected_fault = definition.expected.diagnosis.expected_fault
    measurements = ScenarioMeasurements(
        is_fault_scenario=definition.fault is not None,
        alarm_detected=observed.alarm_count > 0,
        alarm_occurrences=observed.alarm_occurrences,
        incident_count=observed.incident_count,
        diagnosable=diagnosis_expected.required,
        diagnosis_correct=(
            observed.diagnosis_fault == expected_fault.value if expected_fault else diagnosis_ok
        ),
        incident_to_diagnosis_latency_ms=latency_ms,
        evidence_required=evidence_expected.required,
        evidence_sufficient=evidence_ok,
        workflow_required=workflow_expected.required,
        workflow_completed=workflow_ok,
        routing_expected=False,
        routing_correct=False,
        unsafe_case=definition.expected.safety.must_block,
        unsafe_blocked=_unsafe_blocked(definition, observed),
        approval_attempted=definition.execution.approve,
        workorder_created=observed.workorder_count > 0,
        workorder_count=observed.workorder_count,
    )
    return ScenarioResult(
        scenario_id=definition.scenario_id,
        status=status,
        started_at=started_at,
        duration_ms=duration_ms,
        alarm=alarm,
        incident=incident,
        diagnosis=diagnosis,
        evidence=evidence,
        workflow=workflow,
        safety=safety,
        approval=approval,
        workorder=workorder,
        measurements=measurements,
        failures=failures,
    )
