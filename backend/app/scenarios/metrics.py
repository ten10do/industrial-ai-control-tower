"""Aggregate Phase 7 metrics from structured scenario measurements."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict

from app.scenarios.contracts import ComponentStatus, ResultStatus, ScenarioResult


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


class EvaluationMetrics(BaseModel):
    """Rates use scenario counts; compression uses persisted alarm occurrences."""

    model_config = ConfigDict(extra="forbid")

    scenario_total: int
    passed: int
    failed: int
    blocked: int
    detection_rate: float | None
    normal_false_alarm_rate: float | None
    incident_compression: float | None
    diagnosis_accuracy: float | None
    incident_to_diagnosis_latency_median_ms: float | None
    incident_to_diagnosis_latency_p95_ms: float | None
    evidence_sufficiency_rate: float | None
    workflow_completion_rate: float | None
    routing_accuracy: float | None
    unsafe_recommendation_block_rate: float | None
    approval_to_workorder_success_rate: float | None
    workorder_exactly_once_rate: float | None


def compute_metrics(results: list[ScenarioResult]) -> EvaluationMetrics:
    """Compute declared metrics without treating blocked work as success."""

    alarm_runs = [item for item in results if item.alarm.status != ComponentStatus.BLOCKED]
    faults = [item.measurements for item in alarm_runs if item.measurements.is_fault_scenario]
    normals = [item.measurements for item in alarm_runs if not item.measurements.is_fault_scenario]
    compression_runs = [
        item
        for item in results
        if item.alarm.status != ComponentStatus.BLOCKED
        and item.incident.status != ComponentStatus.BLOCKED
    ]
    occurrences = sum(item.measurements.alarm_occurrences for item in compression_runs)
    incidents = sum(item.measurements.incident_count for item in compression_runs)
    diagnosable = [
        item.measurements
        for item in results
        if item.diagnosis.status != ComponentStatus.BLOCKED and item.measurements.diagnosable
    ]
    evidence = [
        item.measurements
        for item in results
        if item.evidence.status != ComponentStatus.BLOCKED and item.measurements.evidence_required
    ]
    workflows = [
        item.measurements
        for item in results
        if item.workflow.status != ComponentStatus.BLOCKED and item.measurements.workflow_required
    ]
    routed = [item for item in workflows if item.routing_expected]
    unsafe = [
        item.measurements
        for item in results
        if item.safety.status != ComponentStatus.BLOCKED and item.measurements.unsafe_case
    ]
    approvals = [
        item.measurements
        for item in results
        if item.approval.status != ComponentStatus.BLOCKED and item.measurements.approval_attempted
    ]
    workorders = [
        item.measurements
        for item in results
        if item.workorder.status != ComponentStatus.BLOCKED and item.measurements.workorder_created
    ]
    latencies = [
        item.incident_to_diagnosis_latency_ms
        for item in diagnosable
        if item.incident_to_diagnosis_latency_ms is not None
    ]
    return EvaluationMetrics(
        scenario_total=len(results),
        passed=sum(item.status == ResultStatus.PASS for item in results),
        failed=sum(item.status == ResultStatus.FAIL for item in results),
        blocked=sum(item.status == ResultStatus.BLOCKED for item in results),
        detection_rate=_rate(sum(item.alarm_detected for item in faults), len(faults)),
        normal_false_alarm_rate=_rate(sum(item.alarm_detected for item in normals), len(normals)),
        incident_compression=(1.0 - incidents / occurrences) if occurrences else None,
        diagnosis_accuracy=_rate(
            sum(item.diagnosis_correct for item in diagnosable), len(diagnosable)
        ),
        incident_to_diagnosis_latency_median_ms=_percentile(latencies, 0.5),
        incident_to_diagnosis_latency_p95_ms=_percentile(latencies, 0.95),
        evidence_sufficiency_rate=_rate(
            sum(item.evidence_sufficient for item in evidence), len(evidence)
        ),
        workflow_completion_rate=_rate(
            sum(item.workflow_completed for item in workflows), len(workflows)
        ),
        routing_accuracy=_rate(sum(item.routing_correct for item in routed), len(routed)),
        unsafe_recommendation_block_rate=_rate(
            sum(item.unsafe_blocked for item in unsafe), len(unsafe)
        ),
        approval_to_workorder_success_rate=_rate(
            sum(item.workorder_created for item in approvals), len(approvals)
        ),
        workorder_exactly_once_rate=_rate(
            sum(item.workorder_count == 1 for item in workorders), len(workorders)
        ),
    )
