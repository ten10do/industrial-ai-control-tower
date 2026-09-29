"""Expectation evaluation and aggregate metric tests."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.knowledge.contracts import IndexArtifact, IndexedChunk, KnowledgeQuery
from app.knowledge.embedding import MODEL_VERSION, embed
from app.knowledge.query import build_query
from app.knowledge.retrieval import KnowledgeIndex
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


def test_waiting_approval_is_the_expected_boundary_when_approval_is_not_requested() -> None:
    payload: Any = valid_definition()
    payload["execution"]["approve"] = False
    observed = ObservedScenario(
        alarm_count=1,
        alarm_severities=["CRITICAL"],
        incident_count=1,
        diagnosis_status="FAULT",
        diagnosis_fault="BEARING_WEAR",
        evidence_sufficiency="SUFFICIENT",
        evidence_count=1,
        workflow_status="WAITING_APPROVAL",
        workflow_provider="openai_compatible",
        policy_decision="REQUIRES_APPROVAL",
        approval_status="PENDING",
    )

    result = evaluate(
        ScenarioDefinition.model_validate(payload), observed, started_at=NOW, duration_ms=10.0
    )

    assert result.status == ResultStatus.PASS
    assert result.workflow.status == ComponentStatus.PASS
    assert result.measurements.workflow_completed is True


def test_waiting_approval_does_not_satisfy_an_approval_scenario() -> None:
    payload: Any = valid_definition()
    payload["execution"]["approve"] = True
    observed = ObservedScenario(
        alarm_count=1,
        alarm_severities=["CRITICAL"],
        incident_count=1,
        diagnosis_status="FAULT",
        diagnosis_fault="BEARING_WEAR",
        evidence_sufficiency="SUFFICIENT",
        evidence_count=1,
        workflow_status="WAITING_APPROVAL",
        workflow_provider="openai_compatible",
        policy_decision="REQUIRES_APPROVAL",
        approval_status="PENDING",
    )

    result = evaluate(
        ScenarioDefinition.model_validate(payload), observed, started_at=NOW, duration_ms=10.0
    )

    assert result.status == ResultStatus.FAIL
    assert result.workflow.status == ComponentStatus.FAIL


def test_real_provider_unavailability_is_an_expected_controlled_failure() -> None:
    payload: Any = valid_definition()
    payload.update(
        {
            "kind": "FAILURE_INJECTION",
            "failure": "LLM_PROVIDER_UNAVAILABLE",
        }
    )
    observed = ObservedScenario(
        alarm_count=1,
        alarm_severities=["CRITICAL"],
        incident_count=1,
        diagnosis_status="FAULT",
        diagnosis_fault="BEARING_WEAR",
        evidence_sufficiency="SUFFICIENT",
        evidence_count=1,
        workflow_status="FAILED",
        workflow_provider="openai_compatible",
    )

    result = evaluate(
        ScenarioDefinition.model_validate(payload), observed, started_at=NOW, duration_ms=10.0
    )

    assert result.status == ResultStatus.PASS


def test_governance_storage_failure_must_be_observed_fail_closed() -> None:
    payload: Any = valid_definition()
    payload.update(
        {
            "kind": "FAILURE_INJECTION",
            "failure": "GOVERNANCE_UNAVAILABLE",
        }
    )
    payload["expected"]["safety"]["must_block"] = True
    payload["expected"]["workorder"] = {"after_approval": False, "max_count": 0}
    observed = ObservedScenario(
        alarm_count=1,
        alarm_severities=["CRITICAL"],
        incident_count=1,
        diagnosis_status="FAULT",
        diagnosis_fault="BEARING_WEAR",
        evidence_sufficiency="SUFFICIENT",
        evidence_count=1,
        governance_error="GOVERNANCE_UNAVAILABLE",
        governance_failed_closed=True,
    )

    result = evaluate(
        ScenarioDefinition.model_validate(payload), observed, started_at=NOW, duration_ms=10.0
    )

    assert result.status == ResultStatus.PASS
    assert result.safety.status == ComponentStatus.PASS


def test_real_retrieval_rejects_the_deterministic_unsupported_query() -> None:
    text = "Inspect motor bearings and verify lubrication before returning equipment to service."
    vector = embed(text)
    index = KnowledgeIndex(
        IndexArtifact(
            index_version="test-index",
            corpus_version="test-corpus",
            corpus_manifest_sha256="0" * 64,
            embedding_model=MODEL_VERSION,
            embedding_dimension=len(vector),
            embedding_normalization="l2",
            created_at=NOW.isoformat(),
            documents=[],
            chunks=[
                IndexedChunk(
                    chunk_id="chunk-1",
                    document_id="doc-1",
                    document_title="Motor manual",
                    text=text,
                    page=1,
                    section="Bearing",
                    heading="Inspection",
                    document_type="manual",
                    equipment_type="industrial_motor",
                    model=None,
                    source="fixture",
                    revision=None,
                    chunk_index=0,
                    content_hash="1" * 64,
                    embedding=vector,
                )
            ],
        )
    )
    query = build_query(
        KnowledgeQuery(
            device_type="industrial_motor",
            fault_type="PHASE7_UNSUPPORTED_FAULT",
            symptoms=["unsupported deterministic acceptance query"],
        )
    )

    result = index.search(query)

    assert result.query.supported_fault is False
    assert str(result.sufficiency.status) == "INSUFFICIENT_EVIDENCE"
