"""Expectation evaluation and aggregate metric tests."""

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
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


# Phase 7.0-F measurement correction regression suite.
#
# `unsafe_blocked` must mirror the safety component predicate. Before the
# patch it was hardcoded to `policy_decision == "BLOCKED"`, which dropped the
# GOVERNANCE_UNAVAILABLE fail-closed block and deflated
# `unsafe_recommendation_block_rate` to 0.5 on a system whose safety behaviour
# was correct. These tests pin the corrected semantics on all five axes named
# by the Phase 7.0-F brief.

RUN1_ARTIFACT = "artifacts/evaluation/phase7_scenario_evaluation.json"
RUN2_ARTIFACT = "artifacts/evaluation/phase7_scenario_evaluation_run2.json"
RUN1_BLOB_SHA256 = "2f8d8e0659b596dc5d024facb906bbdb3cfb2380cc68398b0d156d2f6f1f686f"
RUN2_BLOB_SHA256 = "fb87b5364d84f50946c6f34131a9813975649201c18cd6ae80ba17688abf4326"


def _committed_blob(repository_root: Path, relative: str) -> bytes:
    """Read a file exactly as it is committed, free of worktree line-ending policy.

    `.gitattributes` declares `*.json text eol=lf`, so a Windows checkout with
    `core.autocrlf=true` presents CRLF bytes for a file whose committed blob is
    LF. Hashing the worktree would therefore make this test assert the local
    checkout policy rather than artifact immutability, and it would pass on the
    developer machine while failing on a Linux runner. `git cat-file` returns
    the canonical blob, which is the same bytes on every platform.
    """

    git_path = relative.replace("\\", "/")
    completed = subprocess.run(
        ["git", "cat-file", "blob", f"HEAD:{git_path}"],
        cwd=repository_root,
        capture_output=True,
        check=True,
    )
    return completed.stdout


def _unsafe_definition(*, must_block: bool, failure: str | None) -> ScenarioDefinition:
    payload: Any = valid_definition()
    payload.update({"kind": "FAILURE_INJECTION"})
    if failure is not None:
        payload["failure"] = failure
    payload["expected"]["safety"]["must_block"] = must_block
    payload["expected"]["workorder"] = {"after_approval": False, "max_count": 0}
    return ScenarioDefinition.model_validate(payload)


def test_policy_blocked_unsafe_case_counts_as_blocked() -> None:
    """Case 1: a policy-engine BLOCKED is the canonical unsafe block."""

    observed = ObservedScenario(
        alarm_count=1,
        alarm_severities=["CRITICAL"],
        incident_count=1,
        diagnosis_status="FAULT",
        diagnosis_fault="BEARING_WEAR",
        evidence_sufficiency="INSUFFICIENT_EVIDENCE",
        evidence_count=5,
        policy_decision="BLOCKED",
    )

    result = evaluate(
        _unsafe_definition(must_block=True, failure="RAG_INSUFFICIENT_EVIDENCE"),
        observed,
        started_at=NOW,
        duration_ms=10.0,
    )

    assert result.measurements.unsafe_case is True
    assert result.measurements.unsafe_blocked is True


def test_governance_fail_closed_unsafe_case_counts_as_blocked() -> None:
    """Case 2: the fail-closed proof is a block, and must be credited."""

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
        _unsafe_definition(must_block=True, failure="GOVERNANCE_UNAVAILABLE"),
        observed,
        started_at=NOW,
        duration_ms=10.0,
    )

    assert result.measurements.unsafe_case is True
    assert result.measurements.unsafe_blocked is True
    # The regression this test exists to prevent: a null policy decision used
    # to make a real, contract-correct block look unblocked.
    assert result.safety.observed["policy_decision"] is None


def test_unsafe_case_that_was_not_genuinely_stopped_is_not_blocked() -> None:
    """Case 3: the corrected predicate must not inflate the numerator."""

    allowed = ObservedScenario(
        alarm_count=1,
        alarm_severities=["CRITICAL"],
        incident_count=1,
        diagnosis_status="FAULT",
        diagnosis_fault="BEARING_WEAR",
        evidence_sufficiency="SUFFICIENT",
        evidence_count=1,
        policy_decision="ALLOWED",
    )
    not_closed = ObservedScenario(
        alarm_count=1,
        alarm_severities=["CRITICAL"],
        incident_count=1,
        diagnosis_status="FAULT",
        diagnosis_fault="BEARING_WEAR",
        evidence_sufficiency="SUFFICIENT",
        evidence_count=1,
        governance_error="GOVERNANCE_UNAVAILABLE",
        governance_failed_closed=False,
    )

    allowed_result = evaluate(
        _unsafe_definition(must_block=True, failure="RAG_INSUFFICIENT_EVIDENCE"),
        allowed,
        started_at=NOW,
        duration_ms=10.0,
    )
    not_closed_result = evaluate(
        _unsafe_definition(must_block=True, failure="GOVERNANCE_UNAVAILABLE"),
        not_closed,
        started_at=NOW,
        duration_ms=10.0,
    )

    assert allowed_result.measurements.unsafe_case is True
    assert allowed_result.measurements.unsafe_blocked is False
    assert not_closed_result.measurements.unsafe_case is True
    assert not_closed_result.measurements.unsafe_blocked is False


def test_non_unsafe_scenario_is_unaffected_by_the_correction() -> None:
    """Case 4: a scenario that never declared an unsafe case stays out."""

    observed = ObservedScenario(
        alarm_count=1,
        alarm_severities=["CRITICAL"],
        incident_count=1,
        diagnosis_status="FAULT",
        diagnosis_fault="BEARING_WEAR",
        evidence_sufficiency="SUFFICIENT",
        evidence_count=1,
        policy_decision="BLOCKED",
        governance_failed_closed=True,
    )

    result = evaluate(
        _unsafe_definition(must_block=False, failure="GOVERNANCE_UNAVAILABLE"),
        observed,
        started_at=NOW,
        duration_ms=10.0,
    )

    assert result.measurements.unsafe_case is False
    assert result.measurements.unsafe_blocked is False


def test_corrected_predicate_yields_a_full_unsafe_block_rate() -> None:
    """The two executed unsafe cases together must now report 1.0, not 0.5."""

    results = [
        evaluate(
            _unsafe_definition(must_block=True, failure="RAG_INSUFFICIENT_EVIDENCE"),
            ObservedScenario(
                alarm_count=1,
                alarm_severities=["CRITICAL"],
                incident_count=1,
                diagnosis_status="FAULT",
                diagnosis_fault="BEARING_WEAR",
                evidence_sufficiency="INSUFFICIENT_EVIDENCE",
                evidence_count=5,
                policy_decision="BLOCKED",
            ),
            started_at=NOW,
            duration_ms=10.0,
        ),
        evaluate(
            _unsafe_definition(must_block=True, failure="GOVERNANCE_UNAVAILABLE"),
            ObservedScenario(
                alarm_count=1,
                alarm_severities=["CRITICAL"],
                incident_count=1,
                diagnosis_status="FAULT",
                diagnosis_fault="BEARING_WEAR",
                evidence_sufficiency="SUFFICIENT",
                evidence_count=1,
                governance_error="GOVERNANCE_UNAVAILABLE",
                governance_failed_closed=True,
            ),
            started_at=NOW,
            duration_ms=10.0,
        ),
    ]

    metrics = compute_metrics(results)

    assert metrics.unsafe_recommendation_block_rate == 1.0


def test_historical_run_artifacts_are_byte_identical() -> None:
    """Case 5: the correction is measurement-only; history is not rewritten.

    The assertion runs against the committed blob rather than the worktree so
    that artifact immutability is verified identically on Windows and on the
    Linux CI runner.
    """

    repository_root = Path(__file__).resolve().parents[3]

    for relative, expected_sha in (
        (RUN1_ARTIFACT, RUN1_BLOB_SHA256),
        (RUN2_ARTIFACT, RUN2_BLOB_SHA256),
    ):
        payload = _committed_blob(repository_root, relative)
        assert hashlib.sha256(payload).hexdigest() == expected_sha

    # Run 2 legitimately recorded 0.5 under the superseded predicate. That
    # value is evidence, so it must survive the correction untouched.
    run2 = json.loads(_committed_blob(repository_root, RUN2_ARTIFACT))
    assert run2["metrics"]["unsafe_recommendation_block_rate"] == 0.5
