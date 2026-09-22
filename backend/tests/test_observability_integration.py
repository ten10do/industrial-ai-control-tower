"""Opt-in real-database proof that a real Agent workflow produces observability data.

This test drives the actual ``WorkflowService`` (real LangGraph graph, deterministic
``TestProvider``, real PostgreSQL persistence) through an approval cycle and then
asserts that the observability layer recorded the run, its three agent steps, and
that token columns stayed empty because the deterministic provider reports no
usage.

It is skipped unless ``OBSERVABILITY_TEST_DATABASE_URL`` points at a throwaway
database name, so CI without PostgreSQL remains green. The fixture creates and
drops that database; the live database is never modified.

Example invocation:

    export OBSERVABILITY_TEST_DATABASE_URL="postgresql+asyncpg://postgres:<pw>@localhost:<port>/obs_phase66_test"
    pytest tests/test_observability_integration.py -q
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID

import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infrastructure.database.base import Base
from app.knowledge.contracts import (
    BuiltQuery,
    Citation,
    EvidenceItem,
    KnowledgeSearchResponse,
    SufficiencyAssessment,
    SufficiencyStatus,
)
from app.knowledge.retrieval import DEFAULT_PIPELINE, KnowledgeIndex
from app.models import (
    AgentRun,
    Approval,
    Device,
    Diagnosis,
    Incident,
    ObservabilityMetric,
    ObservabilityRun,
    ObservabilityStep,
    WorkOrder,
)
from app.observability.metrics import build_metrics
from app.observability.repository import ObservabilityRepository
from app.observability.tracer import WORKFLOW_NAME, ObservableWorkflowService, WorkflowTracer
from app.workflow.contracts import WorkflowStatus
from app.workflow.provider import TestProvider
from app.workflow.service import WORKFLOW_VERSION, WorkflowService

DATABASE_URL = os.getenv("OBSERVABILITY_TEST_DATABASE_URL")
DEVICE_ID = "MOTOR-OBS-001"

# This fixture executes ``DROP DATABASE``. That statement is only ever safe
# against a name that is provably disposable, so the target is validated
# against an allow-list instead of being trusted from the environment. A
# mistake here destroys the live database, so the guard is deliberately
# strict: the name must be a plain identifier AND must contain ``test``.
_SAFE_DATABASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*test[a-z0-9_]*$")


def _assert_disposable_database(name: str) -> None:
    """Refuse to reset anything that is not obviously a throwaway database."""
    if not _SAFE_DATABASE_PATTERN.fullmatch(name):
        raise RuntimeError(
            "Refusing to DROP a non-throwaway database. "
            f"OBSERVABILITY_TEST_DATABASE_URL must point at a database whose name "
            f"contains 'test' (for example 'obs_phase66_test'); got {name!r}. "
            "Point the variable at a scratch database instead of the live one."
        )


pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="OBSERVABILITY_TEST_DATABASE_URL is not configured",
)

EVIDENCE = EvidenceItem(
    evidence_id="ev-obs-1",
    document_id="obs-doc-1",
    chunk_id="obs-chunk-1",
    document_title="Observability fixture guidance",
    page=12,
    section="Bearing inspection",
    heading="Bearing wear",
    text="Isolate the drive and inspect the bearing before restarting the motor.",
    retrieval_score=0.91,
    rerank_score=0.88,
    source="fixture",
    revision="R1",
    citation=Citation(
        document="Observability fixture guidance",
        page=12,
        section="Bearing inspection",
        source="fixture",
    ),
)


class StubKnowledgeIndex:
    """Stand-in for ``KnowledgeIndex`` returning one sufficient citation."""

    def __init__(self) -> None:
        self.calls = 0

    def search(
        self,
        query: BuiltQuery,
        *,
        top_k: int = 5,
        pipeline: str = DEFAULT_PIPELINE,
        run_id: UUID | None = None,
    ) -> KnowledgeSearchResponse:
        self.calls += 1
        return KnowledgeSearchResponse(
            retrieval_run_id=run_id,
            pipeline=pipeline,
            corpus_version="observability-test-corpus-v1",
            embedding_version="observability-test-embedding-v1",
            query=query,
            evidence=[EVIDENCE],
            sufficiency=SufficiencyAssessment(
                status=SufficiencyStatus.SUFFICIENT,
                reasons=[],
                top_score=0.91,
                score_margin=0.3,
                supporting_chunks=1,
                source_diversity=1,
                query_coverage=1.0,
                metadata_match=True,
            ),
            latency_ms=12.5,
        )


@pytest_asyncio.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Create an isolated throwaway database for one test and drop it afterwards."""
    assert DATABASE_URL is not None
    url = make_url(DATABASE_URL)
    database = url.database or "obs_phase66_test"
    _assert_disposable_database(database)
    admin_url = url.set(database="postgres")

    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
        await connection.execute(text(f'CREATE DATABASE "{database}"'))
    await admin.dispose()

    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": database},
            )
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
        await admin.dispose()


async def _seed_incident(factory: async_sessionmaker[AsyncSession]) -> tuple[UUID, UUID]:
    async with factory() as session:
        session.add(
            Device(
                device_id=DEVICE_ID,
                device_type="industrial_motor",
                name="Observability fixture motor",
                status="ACTIVE",
            )
        )
        incident = Incident(
            device_id=DEVICE_ID,
            title="Observability fixture incident",
            description="Fixture",
            status="OPEN",
            priority="HIGH",
        )
        session.add(incident)
        await session.flush()
        diagnosis = Diagnosis(
            incident_id=incident.id,
            device_id=DEVICE_ID,
            status="FAULT",
            fault_type="BEARING_WEAR",
            anomaly_score=0.93,
            confidence=0.91,
            severity="HIGH",
            evidence=[
                {
                    "signal": "vibration_mm_s",
                    "observation": 7.4,
                    "normal_baseline": 2.1,
                    "deviation": 5.3,
                    "trend": "increasing",
                }
            ],
            model_version="diagnosis-v1.1",
            feature_version="features-v1",
            trace_id="trace-observability-integration",
        )
        session.add(diagnosis)
        await session.commit()
        return incident.id, diagnosis.id


def _service(factory: async_sessionmaker[AsyncSession]) -> ObservableWorkflowService:
    inner = WorkflowService(
        sessions=factory,
        knowledge_index=cast(KnowledgeIndex, StubKnowledgeIndex()),
        provider=TestProvider(),
        checkpointer=InMemorySaver(),
        max_attempts=3,
        backoff_seconds=0.001,
        timeout_seconds=5,
    )
    return ObservableWorkflowService(inner, WorkflowTracer(factory))


@pytest.mark.asyncio
async def test_real_workflow_produces_observability_data(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    incident_id, diagnosis_id = await _seed_incident(sessions)
    service = _service(sessions)

    workflow = await service.start(incident_id, diagnosis_id, "trace-observability-integration")
    assert workflow.status == WorkflowStatus.WAITING_APPROVAL
    assert workflow.state.approval is None

    async with sessions() as session:
        runs = list(await session.scalars(select(ObservabilityRun)))
        assert len(runs) == 1
        assert runs[0].status == "WAITING_APPROVAL"
        assert runs[0].end_time is None
        assert runs[0].workflow_run_id == workflow.workflow_run_id
        assert runs[0].device_id == DEVICE_ID
        assert runs[0].workflow_name == WORKFLOW_VERSION
        assert WORKFLOW_NAME == WORKFLOW_VERSION
        steps = list(
            await session.scalars(select(ObservabilityStep).order_by(ObservabilityStep.sequence))
        )
        assert [step.agent_name for step in steps] == ["triage", "planning", "safety_review"]
        assert all(step.status == "SUCCESS" for step in steps)
        assert all(step.latency_ms is not None for step in steps)
        assert steps[0].input_summary is not None
        assert steps[1].output_summary is not None
        assert steps[2].output_summary == "hazards=1 violations=0"
        audit_rows = await session.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(AgentRun.workflow_run_id == workflow.workflow_run_id)
        )
        assert audit_rows == 3

    async with sessions() as session:
        pending = await session.scalar(
            select(Approval).where(Approval.workflow_run_id == workflow.workflow_run_id)
        )
        assert pending is not None
        approval_id = pending.id

    decided = await service.decide_approval(
        approval_id,
        decision="APPROVED",
        actor="integration-reviewer",
        reason="Reviewed cited evidence and hazards.",
    )
    assert decided.status == WorkflowStatus.WORK_ORDER_CREATED

    async with sessions() as session:
        run = await session.scalar(select(ObservabilityRun))
        assert run is not None
        assert run.status == "SUCCESS"
        assert run.end_time is not None
        assert run.latency_ms is not None and run.latency_ms > 0
        assert run.result["outcome"] == "SUCCESS"
        assert run.result["step_count"] == 3
        assert run.result["work_order_created"] is True
        assert run.result["decision"] == "APPROVED"

        metrics = list(await session.scalars(select(ObservabilityMetric)))
        assert len(metrics) == 3
        assert all(metric.total_tokens is None for metric in metrics)
        assert all(metric.input_tokens is None for metric in metrics)

        stats = await ObservabilityRepository(session).collect_stats(today_start=run.start_time)
        summary = build_metrics(stats)
        assert summary.total_runs == 1
        assert summary.success_count == 1
        assert summary.failure_count == 0
        assert summary.success_rate == 1.0
        assert summary.step_status_counts == {"SUCCESS": 3}
        assert summary.token_usage.total_tokens is None
        assert summary.token_usage.steps_with_token_data == 0
        assert summary.token_usage.steps_total == 3
        assert summary.avg_latency_ms is not None and summary.avg_latency_ms > 0
        assert summary.p95_latency_ms is not None
        assert [item.agent_name for item in summary.by_agent] == [
            "planning",
            "safety_review",
            "triage",
        ]

        work_order = await session.scalar(select(WorkOrder))
        assert work_order is not None
        assert work_order.status == "DRAFT"
