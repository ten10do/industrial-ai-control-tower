"""Phase 6.6 observability: trace lifecycle, metric derivation, and API contract.

These tests use an in-memory session double and a stubbed repository, so they run
without PostgreSQL. The real-database workflow proof lives in
``tests/test_observability_integration.py`` and is opt-in via an environment
variable.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.api.dependencies import get_session
from app.core.errors import AppError
from app.main import app
from app.models import AgentRun
from app.observability.metrics import (
    AgentAggregate,
    RawObservabilityStats,
    RunCounters,
    RunLatency,
    StepLatency,
    TokenTotals,
    build_metrics,
    percentile,
)
from app.observability.models import (
    ObservabilityMetric,
    ObservabilityRun,
    ObservabilityStatus,
    ObservabilityStep,
    utc_now,
)
from app.observability.repository import ObservabilityRepository
from app.observability.tracer import (
    WORKFLOW_NAME,
    ObservableWorkflowService,
    WorkflowTracer,
    build_step_draft,
    map_workflow_status,
    summarize_input,
    summarize_output,
)
from app.workflow.contracts import (
    DiagnosisSnapshot,
    KnowledgeContextSnapshot,
    WorkflowRead,
    WorkflowState,
    WorkflowStatus,
)
from app.workflow.provider import TestProvider
from app.workflow.service import WorkflowService

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


class FakeResult:
    """Minimal stand-in for a SQLAlchemy ``Result``."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    """In-memory session double covering the observability persistence surface."""

    def __init__(
        self,
        *,
        agent_runs: list[AgentRun] | None = None,
        run: ObservabilityRun | None = None,
        scalars_queue: list[list[Any]] | None = None,
        scalar_queue: list[Any] | None = None,
        execute_queue: list[list[Any]] | None = None,
    ) -> None:
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.commits = 0
        self.run = run
        if scalars_queue is None:
            self.scalars_queue: deque[list[Any]] = deque([agent_runs] if agent_runs else [])
        else:
            self.scalars_queue = deque(scalars_queue)
        self.scalar_queue: deque[Any] = deque(scalar_queue or [])
        self.execute_queue: deque[list[Any]] = deque(execute_queue or [])

    def add(self, instance: Any) -> None:
        self.added.append(instance)
        if isinstance(instance, ObservabilityRun) and instance.run_id is None:
            instance.run_id = uuid4()
        if isinstance(instance, ObservabilityStep) and instance.step_id is None:
            instance.step_id = uuid4()

    async def delete(self, instance: Any) -> None:
        self.deleted.append(instance)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def get(self, model: type[Any], object_id: UUID) -> Any:
        if model is ObservabilityRun:
            return self.run
        return None

    async def scalar(self, statement: Any) -> Any:
        return self.scalar_queue.popleft() if self.scalar_queue else None

    async def scalars(self, statement: Any) -> list[Any]:
        return self.scalars_queue.popleft() if self.scalars_queue else []

    async def execute(self, statement: Any) -> FakeResult:
        return FakeResult(self.execute_queue.popleft() if self.execute_queue else [])


class FakeSessionFactory:
    """``async_sessionmaker`` double yielding one prepared fake session."""

    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self) -> FakeSessionFactory:
        return self

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *exc: object) -> bool:
        return False


class RecordingTracer(WorkflowTracer):
    """Tracer double that records calls instead of touching a database."""

    def __init__(self) -> None:
        self.begun: list[dict[str, Any]] = []
        self.completed: list[dict[str, Any]] = []
        self.refreshed: list[UUID] = []

    async def begin(
        self,
        *,
        device_id: str | None,
        trace_id: str | None,
        provider: str | None,
        model: str | None,
    ) -> UUID | None:
        self.begun.append({"device_id": device_id, "trace_id": trace_id})
        return uuid4()

    async def complete(self, run_id: UUID | None, **kwargs: Any) -> None:
        self.completed.append({"run_id": run_id, **kwargs})

    async def refresh_for_workflow(self, workflow: WorkflowRead, **kwargs: Any) -> None:
        self.refreshed.append(workflow.workflow_run_id)


def workflow_read(status: WorkflowStatus) -> WorkflowRead:
    """Build a minimal authoritative workflow read model."""
    workflow_run_id = uuid4()
    state = WorkflowState(
        workflow_run_id=workflow_run_id,
        trace_id="trace-observability",
        device_id="MOTOR-001",
        incident_id=uuid4(),
        diagnosis_id=uuid4(),
        diagnosis=DiagnosisSnapshot(
            id=uuid4(),
            status="FAULT",
            fault_type="BEARING_WEAR",
            confidence=0.9,
            severity="HIGH",
            model_version="diagnosis-v1.1",
        ),
        sensor_evidence=[],
        knowledge_context=KnowledgeContextSnapshot(sufficiency="SUFFICIENT", evidence=[]),
        provider="test",
        model="deterministic-test-provider-v1",
        prompt_versions={},
        policy_version="safety-policy-v1",
        workflow_version=WORKFLOW_NAME,
    )
    return WorkflowRead(
        workflow_run_id=workflow_run_id,
        incident_id=state.incident_id,
        diagnosis_id=state.diagnosis_id,
        device_id=state.device_id,
        status=status,
        current_stage=status.value,
        workflow_version=WORKFLOW_NAME,
        policy_version="safety-policy-v1",
        provider="test",
        model="deterministic-test-provider-v1",
        state=state,
        created_at=NOW,
        updated_at=NOW,
    )


def agent_run_row(
    *,
    agent_name: str,
    status: str = "SUCCESS",
    latency_ms: float | None = 300.0,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    timestamp: datetime | None = None,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> AgentRun:
    """Build an unpersisted Phase 5 audit row."""
    return AgentRun(
        id=uuid4(),
        workflow_run_id=uuid4(),
        trace_id="trace-observability",
        agent_name=agent_name,
        status=status,
        provider="test",
        model="deterministic-test-provider-v1",
        prompt_version=f"{agent_name}-prompt-v1",
        input_ref="diagnosis-1",
        output_ref=f"workflow:test:{agent_name}",
        tool_calls=[],
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        error=error,
        payload=payload
        if payload is not None
        else {"output": {}, "request_count": 1, "schema_retries": 0},
        timestamp=timestamp or NOW,
    )


def existing_run(**overrides: Any) -> ObservabilityRun:
    """Build an unpersisted observability run row."""
    values: dict[str, Any] = {
        "run_id": uuid4(),
        "workflow_run_id": None,
        "workflow_name": WORKFLOW_NAME,
        "device_id": None,
        "trace_id": "trace-observability",
        "provider": "test",
        "model": "deterministic-test-provider-v1",
        "status": "RUNNING",
        "start_time": utc_now() - timedelta(seconds=2),
        "result": {},
    }
    values.update(overrides)
    return ObservabilityRun(**values)


def plain_service() -> WorkflowService:
    """Build a service that fails before persisting anything."""
    return WorkflowService(
        sessions=cast(Any, None),
        knowledge_index=None,
        provider=TestProvider(),
        checkpointer=InMemorySaver(),
        max_attempts=3,
        backoff_seconds=0.001,
        timeout_seconds=2,
    )


# --------------------------------------------------------------------------- #
# Status mapping
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (WorkflowStatus.CREATED, ObservabilityStatus.RUNNING),
        (WorkflowStatus.TRIAGING, ObservabilityStatus.RUNNING),
        (WorkflowStatus.SAFETY_REVIEW, ObservabilityStatus.RUNNING),
        (WorkflowStatus.WAITING_APPROVAL, ObservabilityStatus.WAITING_APPROVAL),
        (WorkflowStatus.REQUIRES_APPROVAL, ObservabilityStatus.WAITING_APPROVAL),
        (WorkflowStatus.BLOCKED, ObservabilityStatus.BLOCKED),
        (WorkflowStatus.WORK_ORDER_CREATED, ObservabilityStatus.SUCCESS),
        (WorkflowStatus.AUTO_ALLOWED, ObservabilityStatus.SUCCESS),
        (WorkflowStatus.APPROVED, ObservabilityStatus.SUCCESS),
        (WorkflowStatus.REJECTED, ObservabilityStatus.SUCCESS),
        (WorkflowStatus.CANCELLED, ObservabilityStatus.CANCELLED),
        (WorkflowStatus.FAILED, ObservabilityStatus.FAILED),
    ],
)
def test_status_mapping_covers_the_authoritative_lifecycle(
    status: WorkflowStatus, expected: ObservabilityStatus
) -> None:
    assert map_workflow_status(status) == expected


def test_status_mapping_is_exhaustive_over_workflow_status() -> None:
    """Every authoritative status must map without raising."""
    for status in WorkflowStatus:
        assert isinstance(map_workflow_status(status), ObservabilityStatus)


# --------------------------------------------------------------------------- #
# Step materialisation
# --------------------------------------------------------------------------- #


def test_step_draft_records_real_tokens_and_derives_timestamps() -> None:
    row = agent_run_row(agent_name="planning", latency_ms=800.0, input_tokens=120, output_tokens=45)
    draft = build_step_draft(row, sequence=1)
    assert draft.agent_name == "planning"
    assert draft.sequence == 1
    assert draft.status == "SUCCESS"
    assert draft.end_time == NOW
    assert draft.start_time == NOW - timedelta(milliseconds=800.0)
    assert draft.latency_ms == 800.0
    assert (draft.input_tokens, draft.output_tokens, draft.total_tokens) == (120, 45, 165)
    assert draft.source_agent_run_id == row.id


def test_step_draft_leaves_tokens_empty_when_provider_reports_nothing() -> None:
    """Absent provider usage must stay ``None``; it must never become zero."""
    draft = build_step_draft(agent_run_row(agent_name="triage", input_tokens=None), sequence=0)
    assert draft.input_tokens is None
    assert draft.output_tokens is None
    assert draft.total_tokens is None


def test_step_draft_maps_audit_failure_to_failed_step() -> None:
    row = agent_run_row(agent_name="safety_review", status="FAILURE", error="ProviderTimeout: slow")
    draft = build_step_draft(row, sequence=2)
    assert draft.status == "FAILED"
    assert draft.error == "ProviderTimeout: slow"


def test_summaries_are_bounded_and_exclude_prompt_content() -> None:
    planning = summarize_output(
        "planning",
        {
            "objective": "Restore bearing lubrication",
            "steps": [
                {"action": "Lock out", "action_type": "LOCKOUT_TAGOUT"},
                {"action": "Inspect", "action_type": "INSPECT"},
            ],
            "chain_of_thought": "internal reasoning that must not be exposed",
        },
    )
    assert planning is not None
    assert "steps=2" in planning
    assert "LOCKOUT_TAGOUT" in planning
    assert "internal reasoning" not in planning
    assert summarize_output("planning", {}) is None
    assert (
        summarize_output("safety_review", {"hazards": ["A"], "violations": []})
        == "hazards=1 violations=0"
    )
    long_summary = summarize_output("triage", {"problem_summary": "x" * 5_000})
    assert long_summary is not None
    assert len(long_summary) <= 400
    assert long_summary.endswith("...")


def test_input_summary_records_identifiers_only() -> None:
    summary = summarize_input("triage", "diagnosis-9", {"request_count": 2})
    assert summary == "agent=triage diagnosis=diagnosis-9 requests=2"


# --------------------------------------------------------------------------- #
# Trace lifecycle
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_begin_opens_a_running_traced_run() -> None:
    session = FakeSession()
    tracer = WorkflowTracer(cast(Any, FakeSessionFactory(session)))
    run_id = await tracer.begin(
        device_id=None, trace_id="trace-observability", provider="test", model="test-model"
    )
    assert run_id is not None
    created = [item for item in session.added if isinstance(item, ObservabilityRun)]
    assert len(created) == 1
    assert created[0].status == ObservabilityStatus.RUNNING.value
    assert created[0].workflow_name == WORKFLOW_NAME
    assert created[0].end_time is None
    assert created[0].device_id is None
    assert session.commits == 1


@pytest.mark.asyncio
async def test_complete_links_the_run_saves_steps_and_finalizes_status() -> None:
    run = existing_run()
    audit_rows = [
        agent_run_row(agent_name="triage", latency_ms=300.0, timestamp=NOW),
        agent_run_row(
            agent_name="planning",
            latency_ms=800.0,
            timestamp=NOW + timedelta(seconds=1),
            input_tokens=100,
            output_tokens=50,
            payload={
                "output": {"objective": "Inspect", "steps": []},
                "request_count": 1,
                "schema_retries": 0,
            },
        ),
    ]
    session = FakeSession(agent_runs=audit_rows, run=run, scalar_queue=[None])
    tracer = WorkflowTracer(cast(Any, FakeSessionFactory(session)))
    workflow = workflow_read(WorkflowStatus.WORK_ORDER_CREATED)
    await tracer.complete(run.run_id, workflow=workflow, result={"work_order_created": True})

    assert run.workflow_run_id == workflow.workflow_run_id
    assert run.device_id == "MOTOR-001"
    assert run.status == ObservabilityStatus.SUCCESS.value
    assert run.end_time is not None
    assert run.latency_ms is not None and run.latency_ms > 0
    assert run.result["outcome"] == "SUCCESS"
    assert run.result["step_count"] == 2

    steps = [item for item in session.added if isinstance(item, ObservabilityStep)]
    assert [step.agent_name for step in steps] == ["triage", "planning"]
    assert [step.sequence for step in steps] == [0, 1]
    metrics = [item for item in session.added if isinstance(item, ObservabilityMetric)]
    assert [item.total_tokens for item in metrics] == [None, 150]
    assert session.commits == 1


@pytest.mark.asyncio
async def test_complete_keeps_waiting_approval_open() -> None:
    run = existing_run()
    session = FakeSession(run=run, scalar_queue=[None])
    tracer = WorkflowTracer(cast(Any, FakeSessionFactory(session)))
    workflow = workflow_read(WorkflowStatus.WAITING_APPROVAL)
    await tracer.complete(run.run_id, workflow=workflow, result={})
    assert run.status == ObservabilityStatus.WAITING_APPROVAL.value
    assert run.end_time is None
    assert run.latency_ms is None


@pytest.mark.asyncio
async def test_complete_records_blocked_and_failed_outcomes() -> None:
    blocked_run = existing_run()
    blocked = WorkflowTracer(
        cast(Any, FakeSessionFactory(FakeSession(run=blocked_run, scalar_queue=[None])))
    )
    await blocked.complete(
        blocked_run.run_id, workflow=workflow_read(WorkflowStatus.BLOCKED), result={}
    )
    assert blocked_run.status == ObservabilityStatus.BLOCKED.value
    assert blocked_run.end_time is not None

    failed_run = existing_run()
    failing = WorkflowTracer(cast(Any, FakeSessionFactory(FakeSession(run=failed_run))))
    await failing.complete(
        failed_run.run_id,
        workflow=None,
        result={"incident_id": "i"},
        error_message="AppError: Agent workflow failed.",
        status=ObservabilityStatus.FAILED,
    )
    assert failed_run.status == ObservabilityStatus.FAILED.value
    assert failed_run.error_message == "AppError: Agent workflow failed."
    assert failed_run.workflow_run_id is None


@pytest.mark.asyncio
async def test_complete_drops_a_provisional_run_for_an_idempotent_replay() -> None:
    """A replay must not create a second trace for the same workflow execution."""
    workflow = workflow_read(WorkflowStatus.WORK_ORDER_CREATED)
    original = existing_run(workflow_run_id=workflow.workflow_run_id)
    provisional = existing_run()
    session = FakeSession(run=provisional, scalars_queue=[[]], scalar_queue=[original])
    tracer = WorkflowTracer(cast(Any, FakeSessionFactory(session)))
    await tracer.complete(provisional.run_id, workflow=workflow, result={})
    assert session.deleted == [provisional]
    assert original.status == ObservabilityStatus.SUCCESS.value


@pytest.mark.asyncio
async def test_tracer_failures_never_propagate() -> None:
    """Observability must not be able to break the maintenance decision path."""

    class ExplodingFactory:
        def __call__(self) -> ExplodingFactory:
            return self

        async def __aenter__(self) -> Any:
            raise RuntimeError("database down")

        async def __aexit__(self, *exc: object) -> bool:
            return False

    tracer = WorkflowTracer(cast(Any, ExplodingFactory()))
    assert await tracer.begin(device_id=None, trace_id=None, provider=None, model=None) is None
    await tracer.complete(None, workflow=None, result={})
    await tracer.refresh_for_workflow(workflow_read(WorkflowStatus.APPROVED), result={})


@pytest.mark.asyncio
async def test_refresh_finalizes_an_approved_run() -> None:
    workflow = workflow_read(WorkflowStatus.APPROVED)
    run = existing_run(workflow_run_id=workflow.workflow_run_id, status="WAITING_APPROVAL")
    session = FakeSession(
        run=run, agent_runs=[agent_run_row(agent_name="triage")], scalar_queue=[run]
    )
    tracer = WorkflowTracer(cast(Any, FakeSessionFactory(session)))
    await tracer.refresh_for_workflow(workflow, result={"decision": "APPROVED"})
    assert run.status == ObservabilityStatus.SUCCESS.value
    assert run.end_time is not None
    assert run.result["decision"] == "APPROVED"


@pytest.mark.asyncio
async def test_refresh_preserves_the_earlier_result_payload() -> None:
    """Finalising after approval must not discard the recorded run context."""
    workflow = workflow_read(WorkflowStatus.APPROVED)
    run = existing_run(
        workflow_run_id=workflow.workflow_run_id,
        status="WAITING_APPROVAL",
        result={"incident_id": "incident-1", "diagnosis_id": "diagnosis-1"},
    )
    session = FakeSession(run=run, scalar_queue=[run])
    tracer = WorkflowTracer(cast(Any, FakeSessionFactory(session)))
    await tracer.refresh_for_workflow(workflow, result={"decision": "APPROVED"})
    assert run.result["incident_id"] == "incident-1"
    assert run.result["diagnosis_id"] == "diagnosis-1"
    assert run.result["decision"] == "APPROVED"
    assert run.result["outcome"] == "SUCCESS"


@pytest.mark.asyncio
async def test_refresh_ignores_a_workflow_without_a_trace() -> None:
    workflow = workflow_read(WorkflowStatus.APPROVED)
    session = FakeSession(scalar_queue=[None])
    tracer = WorkflowTracer(cast(Any, FakeSessionFactory(session)))
    await tracer.refresh_for_workflow(workflow, result={})
    assert session.added == []
    assert session.commits == 0


# --------------------------------------------------------------------------- #
# Non-invasive workflow integration
# --------------------------------------------------------------------------- #


def test_observable_service_overrides_only_lifecycle_methods() -> None:
    """The wrapper must not replace graph, policy, approval, or RAG behaviour."""
    overridden = {name for name in vars(ObservableWorkflowService) if not name.startswith("_")}
    assert overridden == {"start", "decide_approval", "cancel"}
    assert issubclass(ObservableWorkflowService, WorkflowService)


@pytest.mark.asyncio
async def test_observable_service_records_failure_and_reraises_unchanged() -> None:
    tracer = RecordingTracer()
    wrapper = ObservableWorkflowService(plain_service(), tracer)
    with pytest.raises(AppError, match="Knowledge index is not available"):
        await wrapper.start(uuid4(), uuid4(), "trace-observability")
    assert len(tracer.begun) == 1
    assert tracer.begun[0]["trace_id"] == "trace-observability"
    assert len(tracer.completed) == 1
    assert tracer.completed[0]["status"] == ObservabilityStatus.FAILED
    assert tracer.completed[0]["workflow"] is None
    assert "Knowledge index is not available" in str(tracer.completed[0]["error_message"])


@pytest.mark.asyncio
async def test_observable_service_records_success_and_returns_the_same_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = workflow_read(WorkflowStatus.WAITING_APPROVAL)

    async def fake_start(
        self: WorkflowService, incident_id: UUID, diagnosis_id: UUID, trace_id: str
    ) -> WorkflowRead:
        return expected

    monkeypatch.setattr(WorkflowService, "start", fake_start)
    tracer = RecordingTracer()
    wrapper = ObservableWorkflowService(plain_service(), tracer)
    result = await wrapper.start(uuid4(), uuid4(), "trace-observability")
    assert result is expected
    assert tracer.completed[0]["workflow"] is expected
    assert tracer.completed[0]["run_id"] is not None


@pytest.mark.asyncio
async def test_observable_service_refreshes_after_approval_and_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved = workflow_read(WorkflowStatus.APPROVED)

    async def fake_decide(
        self: WorkflowService, approval_id: UUID, *, decision: str, actor: str, reason: str
    ) -> WorkflowRead:
        return approved

    async def fake_cancel(self: WorkflowService, workflow_id: UUID) -> WorkflowRead:
        return approved

    monkeypatch.setattr(WorkflowService, "decide_approval", fake_decide)
    monkeypatch.setattr(WorkflowService, "cancel", fake_cancel)
    tracer = RecordingTracer()
    wrapper = ObservableWorkflowService(plain_service(), tracer)
    await wrapper.decide_approval(uuid4(), decision="APPROVED", actor="operator", reason="reviewed")
    await wrapper.cancel(uuid4())
    assert tracer.refreshed == [approved.workflow_run_id, approved.workflow_run_id]


# --------------------------------------------------------------------------- #
# Metric derivation
# --------------------------------------------------------------------------- #


def test_percentile_uses_nearest_rank() -> None:
    assert percentile([], 0.95) is None
    assert percentile([10.0], 0.95) == 10.0
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.95) == 40.0
    assert percentile([10.0, 20.0, 30.0, 40.0], 0.0) == 10.0


def test_metrics_derive_success_rate_latency_and_tokens() -> None:
    raw = RawObservabilityStats(
        counters=RunCounters(
            total_runs=10,
            runs_running=1,
            runs_waiting_approval=2,
            runs_today=6,
            success_count=5,
            failure_count=1,
            blocked_count=1,
            cancelled_count=0,
        ),
        run_latency=RunLatency(avg_ms=2400.0, samples_ms=[1000.0, 2000.0, 2400.0, 9000.0]),
        step_latency=StepLatency(avg_ms=500.0),
        tokens=TokenTotals(
            input_tokens=200_000,
            output_tokens=150_000,
            total_tokens=350_000,
            steps_with_token_data=4,
            steps_total=5,
        ),
        step_status_counts={"SUCCESS": 7, "FAILED": 1},
        by_agent=[
            AgentAggregate(
                agent_name="planning",
                steps_total=2,
                failures=0,
                latency_sum_ms=1600.0,
                latency_count=2,
                latency_samples_ms=[800.0, 800.0],
                total_tokens=150,
                schema_retries=0,
            )
        ],
    )
    metrics = build_metrics(raw)
    assert metrics.total_runs == 10
    assert metrics.completed_runs == 7
    assert metrics.success_rate == pytest.approx(5 / 7)
    assert metrics.failure_count == 1
    assert metrics.blocked_count == 1
    assert metrics.cancelled_count == 0
    assert metrics.avg_latency_ms == 2400.0
    assert metrics.p95_latency_ms == 9000.0
    assert metrics.avg_step_latency_ms == 500.0
    assert metrics.step_status_counts == {"SUCCESS": 7, "FAILED": 1}
    assert metrics.token_usage.total_tokens == 350_000
    assert metrics.token_usage.steps_with_token_data == 4
    assert metrics.token_usage.steps_total == 5
    assert metrics.by_agent[0].avg_latency_ms == 800.0
    assert metrics.by_agent[0].total_tokens == 150


def test_metrics_report_absent_values_instead_of_zero() -> None:
    """No completed runs and no provider usage must not be reported as 0."""
    metrics = build_metrics(
        RawObservabilityStats(counters=RunCounters(total_runs=3, runs_running=3))
    )
    assert metrics.success_rate is None
    assert metrics.avg_latency_ms is None
    assert metrics.p95_latency_ms is None
    assert metrics.avg_step_latency_ms is None
    assert metrics.token_usage.input_tokens is None
    assert metrics.token_usage.output_tokens is None
    assert metrics.token_usage.total_tokens is None
    assert metrics.token_usage.steps_with_token_data == 0


def test_metrics_completed_runs_without_success_is_zero_rate() -> None:
    metrics = build_metrics(
        RawObservabilityStats(counters=RunCounters(total_runs=2, failure_count=2))
    )
    assert metrics.success_rate == 0.0


# --------------------------------------------------------------------------- #
# REST contract
# --------------------------------------------------------------------------- #


class _FakeDatabaseSession:
    """Session double for endpoints whose repository calls are stubbed."""

    async def scalars(self, statement: Any) -> list[Any]:
        return []


def _client() -> TestClient:
    async def override_session() -> Any:
        yield _FakeDatabaseSession()

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def _close() -> None:
    app.dependency_overrides.clear()


def test_list_runs_returns_run_history(monkeypatch: pytest.MonkeyPatch) -> None:
    workflow_run_id, run_id = uuid4(), uuid4()
    row = existing_run(
        run_id=run_id,
        workflow_run_id=workflow_run_id,
        device_id="MOTOR-001",
        status="SUCCESS",
        end_time=NOW,
        latency_ms=2400.0,
        result={"outcome": "SUCCESS"},
    )

    async def fake_list(
        self: ObservabilityRepository,
        *,
        limit: int = 50,
        status: str | None = None,
        workflow_name: str | None = None,
    ) -> list[ObservabilityRun]:
        return [row]

    async def fake_counts(self: ObservabilityRepository, run_ids: Any) -> dict[UUID, int]:
        return {run_id: 3}

    async def fake_tokens(self: ObservabilityRepository, run_ids: Any) -> dict[UUID, int | None]:
        return {run_id: 350}

    monkeypatch.setattr(ObservabilityRepository, "list_runs", fake_list)
    monkeypatch.setattr(ObservabilityRepository, "step_counts", fake_counts)
    monkeypatch.setattr(ObservabilityRepository, "token_totals_by_run", fake_tokens)
    try:
        response = _client().get("/api/observability/runs?limit=10")
    finally:
        _close()

    assert response.status_code == 200
    body = response.json()[0]
    assert body["run_id"] == str(run_id)
    assert body["workflow_run_id"] == str(workflow_run_id)
    assert body["workflow_name"] == WORKFLOW_NAME
    assert body["device_id"] == "MOTOR-001"
    assert body["status"] == "SUCCESS"
    assert body["latency_ms"] == 2400.0
    assert body["step_count"] == 3
    assert body["total_tokens"] == 350


def test_run_detail_returns_the_ordered_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = uuid4()
    row = existing_run(
        run_id=run_id, workflow_run_id=uuid4(), status="WAITING_APPROVAL", device_id="MOTOR-001"
    )
    steps = [
        (
            ObservabilityStep(
                step_id=uuid4(),
                run_id=run_id,
                sequence=index,
                agent_name=name,
                status="SUCCESS",
                start_time=NOW,
                end_time=NOW + timedelta(milliseconds=latency),
                latency_ms=float(latency),
            ),
            ObservabilityMetric(
                step_id=uuid4(),
                run_id=run_id,
                agent_name=name,
                input_tokens=tokens,
                output_tokens=None,
                total_tokens=tokens,
                latency_ms=float(latency),
            ),
        )
        for index, (name, latency, tokens) in enumerate(
            [("triage", 300, 10), ("planning", 800, 20), ("safety_review", 250, None)]
        )
    ]

    async def fake_get(self: ObservabilityRepository, requested: UUID) -> ObservabilityRun:
        return row

    async def fake_steps(self: ObservabilityRepository, requested: UUID) -> list[Any]:
        return steps

    monkeypatch.setattr(ObservabilityRepository, "get_run", fake_get)
    monkeypatch.setattr(ObservabilityRepository, "list_steps", fake_steps)
    try:
        response = _client().get(f"/api/observability/runs/{run_id}")
    finally:
        _close()

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["run_id"] == str(run_id)
    assert body["run"]["step_count"] == 3
    assert body["run"]["total_tokens"] == 30
    assert [step["agent_name"] for step in body["steps"]] == [
        "triage",
        "planning",
        "safety_review",
    ]
    assert [step["latency_ms"] for step in body["steps"]] == [300.0, 800.0, 250.0]
    assert body["steps"][2]["metrics"]["token_data_available"] is False


def test_run_detail_returns_404_for_an_unknown_run(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(self: ObservabilityRepository, requested: UUID) -> None:
        return None

    monkeypatch.setattr(ObservabilityRepository, "get_run", fake_get)
    try:
        response = _client().get(f"/api/observability/runs/{uuid4()}")
    finally:
        _close()

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_RUN_NOT_FOUND"


def test_metrics_endpoint_reports_the_dashboard_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_stats(
        self: ObservabilityRepository, *, today_start: datetime
    ) -> RawObservabilityStats:
        return RawObservabilityStats(
            counters=RunCounters(
                total_runs=128,
                runs_today=128,
                runs_waiting_approval=2,
                success_count=93,
                failure_count=3,
                blocked_count=1,
                cancelled_count=2,
            ),
            run_latency=RunLatency(avg_ms=2400.0, samples_ms=[2400.0]),
            tokens=TokenTotals(
                input_tokens=200_000,
                output_tokens=150_000,
                total_tokens=350_000,
                steps_with_token_data=3,
                steps_total=3,
            ),
        )

    monkeypatch.setattr(ObservabilityRepository, "collect_stats", fake_stats)
    try:
        response = _client().get("/api/observability/metrics")
    finally:
        _close()

    assert response.status_code == 200
    body = response.json()
    assert body["total_runs"] == 128
    assert body["runs_today"] == 128
    assert body["failure_count"] == 3
    assert body["success_rate"] == pytest.approx(93 / 99)
    assert body["avg_latency_ms"] == 2400.0
    assert body["token_usage"]["total_tokens"] == 350_000


def test_runs_endpoint_rejects_an_unknown_status_filter() -> None:
    try:
        response = _client().get("/api/observability/runs?status=NOT_A_STATUS")
    finally:
        _close()
    assert response.status_code == 422


@pytest.mark.parametrize(
    "prefix", ["/api/observability", "/api/v1/observability"], ids=["spec", "v1"]
)
def test_observability_endpoints_are_served_under_both_prefixes(
    monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    """The API contract namespace and the Phase 6.6 shorthand must agree."""

    async def fake_list(
        self: ObservabilityRepository,
        *,
        limit: int = 50,
        status: str | None = None,
        workflow_name: str | None = None,
    ) -> list[ObservabilityRun]:
        return []

    async def fake_stats(
        self: ObservabilityRepository, *, today_start: datetime
    ) -> RawObservabilityStats:
        return RawObservabilityStats()

    monkeypatch.setattr(ObservabilityRepository, "list_runs", fake_list)
    monkeypatch.setattr(ObservabilityRepository, "collect_stats", fake_stats)
    try:
        runs = _client().get(f"{prefix}/runs")
        metrics = _client().get(f"{prefix}/metrics")
    finally:
        _close()
    assert runs.status_code == 200
    assert runs.json() == []
    assert metrics.status_code == 200
    assert metrics.json()["total_runs"] == 0
    assert metrics.json()["token_usage"]["total_tokens"] is None


def test_integration_fixture_refuses_to_drop_a_live_database() -> None:
    """The Throwaway-database guard must reject anything that is not scratch.

    ``test_observability_integration`` issues ``DROP DATABASE`` against the name
    taken from ``OBSERVABILITY_TEST_DATABASE_URL``. A copy-paste of the live
    connection string would therefore destroy the live database, so the guard is
    pinned here where it always runs, instead of only inside the opt-in test.
    """
    from tests.test_observability_integration import _assert_disposable_database

    for live_name in (
        "industrial_ai_control_tower",
        "postgres",
        "template0",
        "production",
        "",
    ):
        with pytest.raises(RuntimeError):
            _assert_disposable_database(live_name)
    # A legitimate scratch database name is accepted.
    _assert_disposable_database("obs_phase66_test")
