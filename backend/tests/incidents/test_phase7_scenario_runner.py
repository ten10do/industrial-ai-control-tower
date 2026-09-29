"""DB-backed proof that ScenarioRunner uses the canonical production path."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.knowledge.contracts import IndexArtifact, IndexedChunk, KnowledgeQuery
from app.knowledge.embedding import MODEL_VERSION, embed
from app.knowledge.query import build_query
from app.knowledge.retrieval import KnowledgeIndex
from app.ml.runtime import ModelRuntime
from app.models import Approval, Diagnosis, Incident, Telemetry, WorkflowRun
from app.scenarios.contracts import ScenarioDefinition
from app.scenarios.runner import ScenarioRunner
from app.services.diagnosis import OnlineDiagnosisCoordinator
from app.workflow.provider import OpenAICompatibleProvider
from app.workflow.service import WorkflowService
from tests.incidents.conftest import create_device, seed_rule


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    async def eval(self, script: str, keys: int, key: str, epoch: float, payload: str) -> int:
        current = self.values.get(f"{key}:epoch")
        if current is not None and float(current) >= epoch:
            return 0
        self.values[f"{key}:epoch"] = str(epoch).encode()
        self.values[f"{key}:payload"] = payload.encode()
        return 1

    async def hget(self, key: str, field: str) -> bytes | None:
        return self.values.get(f"{key}:{field}")


def scenario() -> ScenarioDefinition:
    return ScenarioDefinition.model_validate(
        {
            "scenario_id": "db_backed_bearing",
            "description": "DB-backed bearing scenario",
            "kind": "PROGRESSIVE_FAULT",
            "device": {"device_id": "PH7-DB-001", "seed": 501},
            "fault": {"type": "BEARING_WEAR", "severity": 1.0},
            "execution": {
                "warmup_seconds": 20,
                "fault_duration_seconds": 30,
                "recovery_seconds": 5,
            },
            "expected": {
                "alarm": {"required": True, "max_instances": 2},
                "incident": {"required": True, "max_count": 1},
                "diagnosis": {"expected_fault": "BEARING_WEAR"},
                "evidence": {},
                "workflow": {},
                "safety": {},
                "workorder": {},
            },
        }
    )


@pytest.mark.asyncio
async def test_runner_persists_simulator_data_and_correlates_real_incident(
    session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await seed_rule(
        session,
        "HIGH_TEMPERATURE",
        signal_name="temperature",
        threshold=90.0,
        severity="CRITICAL",
    )
    await seed_rule(
        session,
        "HIGH_VIBRATION",
        signal_name="vibration",
        threshold=7.0,
        severity="MAJOR",
    )
    await session.commit()
    backend = Path(__file__).parents[2]
    runtime = ModelRuntime.load(
        backend / "artifacts" / "diagnosis-v1.1.joblib",
        backend / "artifacts" / "model_manifest-v1.1.json",
    )
    runner = ScenarioRunner(
        sessions=sessions,
        redis=FakeRedis(),  # type: ignore[arg-type]
        diagnosis=OnlineDiagnosisCoordinator(runtime, sessions),
        knowledge_index=None,
        workflow=None,
    )

    result = await runner.run(scenario())

    telemetry_count = int(await session.scalar(select(func.count()).select_from(Telemetry)) or 0)
    incident_count = int(await session.scalar(select(func.count()).select_from(Incident)) or 0)
    assert telemetry_count == 66
    assert incident_count == 1
    assert result.alarm.observed["count"] >= 1
    assert result.incident.observed["count"] == 1
    assert result.workflow.status == "BLOCKED"


def test_recovery_samples_cover_the_complete_fault_envelope() -> None:
    definition = ScenarioDefinition.model_validate(
        {
            "scenario_id": "recovery_envelope",
            "description": "Recovery reaches a fully normal sample",
            "kind": "RECOVERY",
            "device": {"device_id": "PH7-RECOVERY-TEST", "seed": 107},
            "fault": {"type": "BEARING_WEAR", "severity": 1.0},
            "execution": {
                "warmup_seconds": 25,
                "fault_duration_seconds": 25,
                "recovery_seconds": 20,
            },
            "expected": {
                "alarm": {"required": True, "cleared_after_recovery": True},
                "incident": {"required": True},
                "diagnosis": {"expected_fault": "BEARING_WEAR"},
                "evidence": {},
                "workflow": {},
                "safety": {},
                "workorder": {},
            },
        }
    )
    runner = object.__new__(ScenarioRunner)

    samples = runner._samples(definition, datetime(2026, 9, 28, tzinfo=UTC))

    assert len(samples) == 81
    assert samples[-1].fault_state == "NORMAL"
    # The frozen simulator's stateful thermal and vibration decay remain above
    # their alarm thresholds even after the fault envelope ends. The harness
    # must not clear those alarms merely because the label changed to NORMAL.
    assert samples[-1].temperature_c > 90.0
    assert samples[-1].vibration_mm_s > 7.0


@pytest.mark.asyncio
async def test_pending_approval_is_selected_by_current_workflow_id(
    session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    device = await create_device(session, "PH7-APPROVAL-001")
    incident = Incident(device_id=device.device_id, title="approval selection")
    session.add(incident)
    await session.flush()
    diagnosis = Diagnosis(
        incident_id=incident.id,
        device_id=device.device_id,
        status="FAULT",
        fault_type="BEARING_WEAR",
    )
    session.add(diagnosis)
    await session.flush()

    def workflow(trace_id: str) -> WorkflowRun:
        return WorkflowRun(
            incident_id=incident.id,
            diagnosis_id=diagnosis.id,
            device_id=device.device_id,
            trace_id=trace_id,
            idempotency_key=f"key-{uuid4()}",
            workflow_version="maintenance-decision-workflow-v1",
            policy_version="safety-policy-v1",
            provider="openai_compatible",
            model="deepseek-flash",
            prompt_versions={},
            status="WAITING_APPROVAL",
            current_stage="WAITING_APPROVAL",
            state={},
            attempt_count=0,
            errors=[],
            plan_version=1,
        )

    unrelated = workflow("phase7:unrelated")
    current = workflow("phase7:failure_duplicate_workflow_request")
    session.add_all([unrelated, current])
    await session.flush()
    unrelated_approval = Approval(workflow_run_id=unrelated.id, decision="PENDING")
    current_approval = Approval(workflow_run_id=current.id, decision="PENDING")
    session.add_all([unrelated_approval, current_approval])
    await session.commit()

    runner = object.__new__(ScenarioRunner)
    runner.sessions = sessions
    selected = await runner._pending_approval(current.id)

    assert selected is not None
    assert selected.id == current_approval.id
    assert selected.id != unrelated_approval.id


@pytest.mark.asyncio
async def test_governance_probe_uses_real_storage_failure_and_fails_closed() -> None:
    error, failed_closed = await ScenarioRunner._governance_failure()

    assert error == "GOVERNANCE_UNAVAILABLE"
    assert failed_closed is True


@pytest.mark.asyncio
async def test_f03_probe_uses_real_retrieval_and_production_precondition_graph() -> None:
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
            created_at=datetime(2026, 9, 28, tzinfo=UTC).isoformat(),
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
    retrieval = index.search(
        build_query(
            KnowledgeQuery(
                fault_type="PHASE7_UNSUPPORTED_FAULT",
                symptoms=["unsupported deterministic acceptance query"],
            )
        )
    )
    diagnosis = Diagnosis(
        id=uuid4(),
        incident_id=uuid4(),
        device_id="PH7-F03-TEST",
        status="FAULT",
        fault_type="OVERHEATING",
        confidence=0.9,
        severity="HIGH",
        evidence=[],
        model_version="diagnosis-v1.1",
    )
    provider = OpenAICompatibleProvider(
        api_key="x",
        base_url="http://127.0.0.1:1/v1",
        model="deepseek-flash",
        temperature=0.0,
        timeout_seconds=0.1,
    )
    workflow = WorkflowService(
        sessions=cast(Any, None),
        knowledge_index=index,
        provider=provider,
        checkpointer=InMemorySaver(),
        max_attempts=1,
        backoff_seconds=0.001,
        timeout_seconds=0.1,
    )

    status, observed_provider, decision = await ScenarioRunner._probe_insufficient_evidence(
        workflow,
        diagnosis,
        retrieval,
        trace_id="phase7:F03:test",
    )

    assert str(retrieval.sufficiency.status) == "INSUFFICIENT_EVIDENCE"
    assert status == "BLOCKED"
    assert observed_provider == "openai_compatible"
    assert decision == "BLOCKED"
