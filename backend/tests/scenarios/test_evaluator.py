"""Expectation evaluation and aggregate metric tests."""

from datetime import UTC, datetime, timedelta

from app.scenarios.contracts import ComponentStatus, ResultStatus, ScenarioDefinition
from app.scenarios.evaluator import ObservedScenario, evaluate
from app.scenarios.metrics import compute_metrics
from tests.scenarios.test_contracts import valid_definition

NOW = datetime(2026, 9, 28, tzinfo=UTC)


def definition() -> ScenarioDefinition:
    return ScenarioDefinition.model_validate(valid_definition())


def test_unavailable_llm_is_blocked_not_passed() -> None:
    observed = ObservedScenario(
        alarm_count=1,
        alarm_occurrences=8,
        alarm_severities=["CRITICAL"],
        incident_count=1,
        incident_created_at=NOW,
        diagnosis_status="FAULT",
        diagnosis_fault="BEARING_WEAR",
        diagnosis_created_at=NOW + timedelta(seconds=2),
        evidence_sufficiency="SUFFICIENT",
        evidence_count=3,
        blocked={
            "workflow": "real LLM unavailable",
            "safety": "not reached",
            "approval": "not reached",
            "workorder": "not reached",
        },
    )
    result = evaluate(definition(), observed, started_at=NOW, duration_ms=10.0)
    assert result.status == ResultStatus.BLOCKED
    assert result.workflow.status == ComponentStatus.BLOCKED
    assert result.measurements.diagnosis_correct is True


def test_metric_formulas_use_raw_counts_and_ignore_blocked_as_success() -> None:
    base = ObservedScenario(
        alarm_count=1,
        alarm_occurrences=10,
        alarm_severities=["CRITICAL"],
        incident_count=1,
        incident_created_at=NOW,
        diagnosis_status="FAULT",
        diagnosis_fault="BEARING_WEAR",
        diagnosis_created_at=NOW + timedelta(seconds=1),
        evidence_sufficiency="SUFFICIENT",
        evidence_count=2,
        workflow_status="BLOCKED",
        workflow_provider="openai_compatible",
        policy_decision="BLOCKED",
        workorder_count=0,
    )
    first = evaluate(definition(), base, started_at=NOW, duration_ms=10.0)
    second = first.model_copy(update={"status": ResultStatus.BLOCKED})
    metrics = compute_metrics([first, second])
    assert metrics.detection_rate == 1.0
    assert metrics.incident_compression == 0.9
    assert metrics.diagnosis_accuracy == 1.0
    assert metrics.incident_to_diagnosis_latency_median_ms == 1000.0
    assert metrics.blocked == 1
