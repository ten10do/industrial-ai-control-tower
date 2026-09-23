"""Phase 6.9-C Incident Operations Center tests.

These are database-backed on purpose. The dashboard's bulk resolution, the
workflow bridge's approval gate, and the metrics averages all depend on real
SQL semantics (averages over epoch extracts, IN-list predicates, the latest-row
choice per incident) that a fake repository would silently reimplement instead
of verify.

The start-workflow endpoint test runs against a minimal FastAPI app with a
fake workflow service: the real engine's graph is Phase 5 territory and the
gate is what this phase owns. The fake records the delegation arguments so the
contract "gate passes, engine receives (incident, diagnosis, trace)" is
checkable without running a single agent step.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_actor, get_session
from app.api.incidents import router as incident_router
from app.incidents.errors import AlarmLifecycleError
from app.incidents.operations import (
    WORKFLOW_ENTRY_STATUSES,
    IncidentNotReadyError,
    IncidentOperationsService,
    IncidentWorkflowGate,
)
from app.models import Alarm, Approval, Diagnosis, Incident, WorkflowRun
from app.workflow.contracts import (
    DiagnosisSnapshot,
    KnowledgeContextSnapshot,
    WorkflowRead,
    WorkflowState,
    WorkflowStatus,
)
from tests.incidents.conftest import create_device, utc

T0 = utc(2026, 9, 23, 10, 0, 0)


async def make_incident(
    session: AsyncSession,
    *,
    device_id: str | None = "MOTOR-001",
    title: str = "incident",
    status: str = "OPEN",
    severity: str | None = "WARNING",
    priority: str = "MEDIUM",
    created_at: datetime = T0,
    acknowledged_at: datetime | None = None,
    acknowledged_by: str | None = None,
    resolved_at: datetime | None = None,
) -> Incident:
    incident = Incident(
        device_id=device_id,
        title=title,
        description="",
        status=status,
        severity=severity,
        priority=priority,
        created_at=created_at,
        updated_at=created_at,
        acknowledged_at=acknowledged_at,
        acknowledged_by=acknowledged_by,
        resolved_at=resolved_at,
    )
    session.add(incident)
    await session.flush()
    return incident


async def make_diagnosis(
    session: AsyncSession,
    incident: Incident,
    *,
    status: str = "FAULT",
    device_id: str | None = "MOTOR-001",
) -> Diagnosis:
    diagnosis = Diagnosis(
        incident_id=incident.id,
        device_id=device_id,
        status=status,
        fault_type="BEARING_WEAR",
        confidence=0.9,
        severity="HIGH",
        evidence=[],
        model_version="diagnosis-v1.1",
    )
    session.add(diagnosis)
    await session.flush()
    return diagnosis


def make_workflow_read(incident_id: UUID, diagnosis_id: UUID) -> WorkflowRead:
    state = WorkflowState(
        workflow_run_id=uuid4(),
        trace_id="trace-operations-test",
        device_id="MOTOR-001",
        incident_id=incident_id,
        diagnosis_id=diagnosis_id,
        diagnosis=DiagnosisSnapshot(
            id=diagnosis_id,
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
        workflow_version="maintenance-decision-workflow-v1",
        status=WorkflowStatus.WAITING_APPROVAL,
        current_stage=WorkflowStatus.WAITING_APPROVAL,
    )
    return WorkflowRead(
        workflow_run_id=state.workflow_run_id,
        incident_id=incident_id,
        diagnosis_id=diagnosis_id,
        device_id="MOTOR-001",
        status=state.status,
        current_stage=state.current_stage,
        workflow_version=state.workflow_version,
        policy_version=state.policy_version,
        provider=state.provider,
        model=state.model,
        state=state,
        created_at=T0,
        updated_at=T0,
    )


async def make_workflow_run(
    session: AsyncSession,
    incident: Incident,
    diagnosis: Diagnosis,
    *,
    status: str = "WAITING_APPROVAL",
) -> WorkflowRun:
    run = WorkflowRun(
        incident_id=incident.id,
        diagnosis_id=diagnosis.id,
        device_id=diagnosis.device_id or "MOTOR-001",
        trace_id="trace-operations-test",
        idempotency_key=f"key-{uuid4()}",
        workflow_version="maintenance-decision-workflow-v1",
        policy_version="safety-policy-v1",
        provider="test",
        model="deterministic-test-provider-v1",
        prompt_versions={},
        status=status,
        current_stage=status,
        state={},
        attempt_count=0,
        errors=[],
        plan_version=1,
    )
    session.add(run)
    await session.flush()
    return run


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_summary_counts_whole_population(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    await make_incident(session, title="open-critical", severity="CRITICAL")  # active, crit, unack
    await make_incident(session, title="open-warning", severity="WARNING")  # active, unack
    await make_incident(
        session,
        title="acked-critical",
        status="ACKNOWLEDGED",
        severity="CRITICAL",
        acknowledged_at=T0 + timedelta(minutes=2),
        acknowledged_by="operator",
    )  # active, crit
    await make_incident(
        session, title="resolved", status="RESOLVED", severity="MAJOR", resolved_at=T0
    )  # neither active nor critical nor unacknowledged

    summary, _ = await IncidentOperationsService(session).dashboard()
    assert summary == {"active": 3, "critical": 2, "unacknowledged": 2}


@pytest.mark.asyncio
async def test_dashboard_rows_resolve_asset_and_workflow_in_bulk(session: AsyncSession) -> None:
    device = await create_device(session, "MOTOR-001")
    device.asset_node_id = uuid4()
    from app.assetconfig.models import AssetNode

    node = AssetNode(id=device.asset_node_id, name="Plant A", asset_type="SITE", parent_id=None)
    session.add(node)
    await session.flush()

    incident = await make_incident(session, title="bearing alarm cluster")
    diagnosis = await make_diagnosis(session, incident)
    run = await make_workflow_run(session, incident, diagnosis, status="WAITING_APPROVAL")

    _, rows = await IncidentOperationsService(session).dashboard()
    assert len(rows) == 1
    row = rows[0]
    assert row["incident_id"] == incident.id
    assert row["device_id"] == "MOTOR-001"
    assert row["asset_name"] == "Plant A"
    assert row["workflow_status"] == "WAITING_APPROVAL"
    assert row["last_alarm_at"] is None
    assert run.id  # the run exists; the row only surfaces its status


@pytest.mark.asyncio
async def test_dashboard_tolerates_deviceless_incidents(session: AsyncSession) -> None:
    await make_incident(session, device_id=None, title="orphan")
    summary, rows = await IncidentOperationsService(session).dashboard()
    assert summary["active"] == 1
    assert rows[0]["device_id"] is None
    assert rows[0]["asset_name"] is None
    assert rows[0]["workflow_status"] is None


@pytest.mark.asyncio
async def test_dashboard_applies_filters(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    await create_device(session, "MOTOR-002")
    await make_incident(session, title="critical-one", severity="CRITICAL")
    await make_incident(session, title="minor-two", device_id="MOTOR-002", severity="MINOR")
    _, rows = await IncidentOperationsService(session).dashboard(severity="CRITICAL")
    assert [row["title"] for row in rows] == ["critical-one"]
    _, rows = await IncidentOperationsService(session).dashboard(device_id="MOTOR-002")
    assert [row["title"] for row in rows] == ["minor-two"]


# ---------------------------------------------------------------------------
# Workflow bridge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_bridge_without_workflow(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    incident = await make_incident(session)
    bridge = await IncidentOperationsService(session).workflow_context(incident.id)
    assert bridge["workflow_exists"] is False
    assert bridge["workflow_run_id"] is None
    assert bridge["workflow_status"] is None
    assert bridge["approval_required"] is False


@pytest.mark.asyncio
async def test_workflow_bridge_reports_pending_human_gate(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    incident = await make_incident(session)
    diagnosis = await make_diagnosis(session, incident)
    run = await make_workflow_run(session, incident, diagnosis, status="WAITING_APPROVAL")
    session.add(Approval(workflow_run_id=run.id, decision="PENDING", plan_version=1))
    await session.flush()

    bridge = await IncidentOperationsService(session).workflow_context(incident.id)
    assert bridge["workflow_exists"] is True
    assert bridge["workflow_run_id"] == run.id
    assert bridge["workflow_status"] == "WAITING_APPROVAL"
    assert bridge["approval_required"] is True


@pytest.mark.asyncio
async def test_workflow_bridge_decided_gate_is_not_pending(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    incident = await make_incident(session)
    diagnosis = await make_diagnosis(session, incident)
    run = await make_workflow_run(session, incident, diagnosis, status="WORK_ORDER_CREATED")
    session.add(
        Approval(
            workflow_run_id=run.id,
            decision="APPROVED",
            actor="operator",
            plan_version=1,
            decided_at=T0,
        )
    )
    await session.flush()

    bridge = await IncidentOperationsService(session).workflow_context(incident.id)
    assert bridge["workflow_status"] == "WORK_ORDER_CREATED"
    assert bridge["approval_required"] is False


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_mtta_mttr_and_compression(session: AsyncSession) -> None:
    device = await create_device(session, "MOTOR-001")
    from app.incidents.models import IncidentAlarm

    acked = await make_incident(
        session,
        title="acked",
        acknowledged_at=T0 + timedelta(seconds=120),
        acknowledged_by="operator",
    )
    resolved = await make_incident(
        session,
        title="resolved",
        status="RESOLVED",
        resolved_at=T0 + timedelta(seconds=3600),
    )
    # 4 alarms across 2 incidents -> compression 2.0
    for index in range(4):
        alarm = Alarm(
            device_id=device.device_id,
            rule_id=f"rule-{index}",
            severity="WARNING",
            status="CLEARED",
            message="m",
            started_at=T0,
            cleared_at=T0,
        )
        session.add(alarm)
        await session.flush()
        session.add(
            IncidentAlarm(incident_id=acked.id if index < 2 else resolved.id, alarm_id=alarm.id)
        )
    await session.flush()

    metrics = await IncidentOperationsService(session).metrics()
    assert metrics["mtta_seconds"] == pytest.approx(120.0)
    assert metrics["mttr_seconds"] == pytest.approx(3600.0)
    assert metrics["alarm_compression"] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_metrics_are_zero_on_empty_database(session: AsyncSession) -> None:
    metrics = await IncidentOperationsService(session).metrics()
    assert metrics == {"mtta_seconds": 0.0, "mttr_seconds": 0.0, "alarm_compression": 0.0}


# ---------------------------------------------------------------------------
# Workflow gate
# ---------------------------------------------------------------------------


def test_workflow_entry_statuses_match_the_transition_table() -> None:
    """The gate derives its statuses from the state module, not a copy."""

    from app.incidents.states import IncidentStatus, is_incident_transition_allowed

    expected = frozenset(
        status
        for status in IncidentStatus
        if is_incident_transition_allowed(status, IncidentStatus.UNDER_ANALYSIS)
    )
    assert expected == WORKFLOW_ENTRY_STATUSES
    # OPEN, ACKNOWLEDGED, and INVESTIGATING may all legally reach the
    # workflow-owned UNDER_ANALYSIS per the transition table.
    assert expected == frozenset(
        {IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED, IncidentStatus.INVESTIGATING}
    )


@pytest.mark.asyncio
async def test_gate_passes_for_open_incident_with_fault_diagnosis(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    incident = await make_incident(session)
    diagnosis = await make_diagnosis(session, incident)
    got_incident, got_diagnosis = await IncidentWorkflowGate(session).ensure_ready(incident.id)
    assert got_incident.id == incident.id
    assert got_diagnosis.id == diagnosis.id


@pytest.mark.asyncio
async def test_gate_passes_for_acknowledged_incident_with_uncertain_diagnosis(
    session: AsyncSession,
) -> None:
    await create_device(session, "MOTOR-001")
    incident = await make_incident(session, status="ACKNOWLEDGED")
    await make_diagnosis(session, incident, status="UNCERTAIN")
    _, got_diagnosis = await IncidentWorkflowGate(session).ensure_ready(incident.id)
    assert got_diagnosis.status == "UNCERTAIN"


@pytest.mark.asyncio
async def test_gate_refuses_without_diagnosis(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    incident = await make_incident(session)
    with pytest.raises(IncidentNotReadyError) as excinfo:
        await IncidentWorkflowGate(session).ensure_ready(incident.id)
    assert excinfo.value.code == "INCIDENT_NOT_READY"
    assert excinfo.value.status_code == 409
    assert excinfo.value.details is not None
    assert excinfo.value.details["reason"] == "DIAGNOSIS"


@pytest.mark.asyncio
async def test_gate_refuses_diagnosis_without_device(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    incident = await make_incident(session)
    await make_diagnosis(session, incident, device_id=None)
    with pytest.raises(IncidentNotReadyError) as excinfo:
        await IncidentWorkflowGate(session).ensure_ready(incident.id)
    assert excinfo.value.details is not None
    assert excinfo.value.details["reason"] == "DIAGNOSIS"


@pytest.mark.asyncio
async def test_gate_refuses_unusable_diagnosis_status(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    incident = await make_incident(session)
    await make_diagnosis(session, incident, status="DRAFT")
    with pytest.raises(IncidentNotReadyError):
        await IncidentWorkflowGate(session).ensure_ready(incident.id)


@pytest.mark.asyncio
async def test_gate_refuses_status_outside_the_entry_set(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    incident = await make_incident(session, status="MITIGATED")
    await make_diagnosis(session, incident, status="FAULT")
    with pytest.raises(IncidentNotReadyError) as excinfo:
        await IncidentWorkflowGate(session).ensure_ready(incident.id)
    assert excinfo.value.details is not None
    assert excinfo.value.details["reason"] == "INCIDENT_STATUS"
    assert excinfo.value.details["current_status"] == "MITIGATED"


@pytest.mark.asyncio
async def test_gate_refuses_unknown_incident_with_404(session: AsyncSession) -> None:
    with pytest.raises(AlarmLifecycleError) as excinfo:
        await IncidentWorkflowGate(session).ensure_ready(uuid4())
    assert excinfo.value.code == "INCIDENT_NOT_FOUND"


# ---------------------------------------------------------------------------
# start-workflow endpoint (gate + delegation, fake engine)
# ---------------------------------------------------------------------------


class FakeWorkflowService:
    """Records delegation; returns a canned WAITING_APPROVAL run."""

    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, str]] = []

    async def start(self, incident_id: UUID, diagnosis_id: UUID, trace_id: str) -> WorkflowRead:
        self.calls.append((incident_id, diagnosis_id, trace_id))
        return make_workflow_read(incident_id, diagnosis_id)


def _app(session: AsyncSession, workflow_service: Any) -> FastAPI:
    from app.core.context import trace_id_context
    from app.core.errors import AppError
    from app.incidents.errors import AlarmLifecycleError
    from app.main import _error_response

    app = FastAPI()
    app.state.workflow_service = workflow_service
    app.include_router(incident_router, prefix="/api/v1")

    @app.exception_handler(AppError)
    async def app_error(request: Any, exc: AppError) -> Any:
        return _error_response(
            exc.code, exc.message, trace_id_context.get(), exc.status_code, exc.details
        )

    @app.exception_handler(AlarmLifecycleError)
    async def lifecycle_error(request: Any, exc: AlarmLifecycleError) -> Any:
        return _error_response(
            exc.code, exc.message, trace_id_context.get(), exc.status_code, exc.details
        )

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_actor] = lambda: "incident-operator"
    return app


@pytest_asyncio.fixture
async def client(
    session: AsyncSession, fake_service: FakeWorkflowService
) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_app(session, fake_service))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest.fixture
def fake_service() -> FakeWorkflowService:
    return FakeWorkflowService()


@pytest.mark.asyncio
async def test_start_workflow_delegates_to_the_engine(
    session: AsyncSession, client: httpx.AsyncClient, fake_service: FakeWorkflowService
) -> None:
    await create_device(session, "MOTOR-001")
    incident = await make_incident(session)
    diagnosis = await make_diagnosis(session, incident)

    response = await client.post(f"/api/v1/incidents/{incident.id}/start-workflow")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "WAITING_APPROVAL"
    assert [(call[0], call[1]) for call in fake_service.calls] == [(incident.id, diagnosis.id)]
    # The gate audited the request against the incident.
    from sqlalchemy import select

    from app.models import AuditEvent

    actions = list(
        await session.scalars(select(AuditEvent).where(AuditEvent.resource == str(incident.id)))
    )
    assert any(row.action == "INCIDENT_WORKFLOW_REQUESTED" for row in actions)


@pytest.mark.asyncio
async def test_start_workflow_refuses_incident_without_diagnosis(
    session: AsyncSession, client: httpx.AsyncClient, fake_service: FakeWorkflowService
) -> None:
    await create_device(session, "MOTOR-001")
    incident = await make_incident(session)

    response = await client.post(f"/api/v1/incidents/{incident.id}/start-workflow")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "INCIDENT_NOT_READY"
    assert error["details"]["reason"] == "DIAGNOSIS"
    assert fake_service.calls == []


@pytest.mark.asyncio
async def test_start_workflow_refuses_unknown_incident(
    session: AsyncSession, client: httpx.AsyncClient, fake_service: FakeWorkflowService
) -> None:
    response = await client.post(f"/api/v1/incidents/{uuid4()}/start-workflow")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INCIDENT_NOT_FOUND"
