"""Read-only query contracts required by the Phase 6 operator UI."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import get_session
from app.main import app
from app.models import Approval, Diagnosis

NOW = datetime(2026, 9, 21, tzinfo=UTC)


class FakeSession:
    def __init__(
        self,
        *,
        scalars: list[list[Any]] | None = None,
        scalar: list[Any] | None = None,
        objects: dict[tuple[type[Any], UUID], Any] | None = None,
    ) -> None:
        self.scalar_results = deque(scalar or [])
        self.scalars_results = deque(scalars or [])
        self.objects = objects or {}

    async def scalars(self, statement: Any) -> list[Any]:
        return self.scalars_results.popleft()

    async def scalar(self, statement: Any) -> Any:
        return self.scalar_results.popleft()

    async def get(self, model: type[Any], object_id: UUID) -> Any:
        return self.objects.get((model, object_id))


def _row(**values: Any) -> SimpleNamespace:
    return SimpleNamespace(**values)


def _request(path: str, session: FakeSession) -> Any:
    async def override_session() -> Any:
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        return TestClient(app).get(path)
    finally:
        app.dependency_overrides.clear()


def test_incident_list_exposes_diagnosis_and_workflow_lifecycle() -> None:
    incident_id, diagnosis_id, workflow_id = uuid4(), uuid4(), uuid4()
    incident = _row(
        id=incident_id,
        device_id="MOTOR-001",
        title="Bearing wear detected",
        status="ACTION_PENDING",
        priority="HIGH",
        created_at=NOW,
        updated_at=NOW,
    )
    diagnosis = _row(
        id=diagnosis_id,
        status="FAULT",
        fault_type="BEARING_WEAR",
        severity="HIGH",
    )
    workflow = _row(id=workflow_id, status="WAITING_APPROVAL")
    response = _request(
        "/api/v1/incidents",
        FakeSession(scalars=[[incident]], scalar=[diagnosis, workflow, None]),
    )

    assert response.status_code == 200
    body = response.json()[0]
    assert body["diagnosis_id"] == str(diagnosis_id)
    assert body["fault_type"] == "BEARING_WEAR"
    assert body["workflow_run_id"] == str(workflow_id)
    assert body["workflow_status"] == "WAITING_APPROVAL"


def test_workflow_list_is_summary_only() -> None:
    workflow_id, incident_id, diagnosis_id = uuid4(), uuid4(), uuid4()
    workflow = _row(
        id=workflow_id,
        incident_id=incident_id,
        diagnosis_id=diagnosis_id,
        device_id="MOTOR-001",
        status="WAITING_APPROVAL",
        current_stage="WAITING_APPROVAL",
        policy_version="safety-policy-v1",
        provider="openai_compatible",
        model="deepseek-flash",
        created_at=NOW,
        updated_at=NOW,
    )
    response = _request("/api/v1/workflows", FakeSession(scalars=[[workflow]]))

    assert response.status_code == 200
    assert response.json()[0] == {
        "workflow_run_id": str(workflow_id),
        "incident_id": str(incident_id),
        "diagnosis_id": str(diagnosis_id),
        "device_id": "MOTOR-001",
        "status": "WAITING_APPROVAL",
        "current_stage": "WAITING_APPROVAL",
        "policy_version": "safety-policy-v1",
        "provider": "openai_compatible",
        "model": "deepseek-flash",
        "created_at": "2026-09-21T00:00:00Z",
        "updated_at": "2026-09-21T00:00:00Z",
    }


def test_work_order_list_includes_auditable_approval_context() -> None:
    work_order_id, workflow_id, incident_id, diagnosis_id, approval_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    order = _row(
        id=work_order_id,
        workflow_run_id=workflow_id,
        incident_id=incident_id,
        diagnosis_id=diagnosis_id,
        device_id="MOTOR-001",
        title="Inspect bearing wear",
        priority="HIGH",
        plan={"objective": "Inspect bearing"},
        evidence_refs=["ev-1"],
        safety_requirements=["HIGH_SEVERITY"],
        approval_id=approval_id,
        status="DRAFT",
        created_at=NOW,
    )
    diagnosis = _row(fault_type="BEARING_WEAR")
    approval = _row(actor="operator-1", decided_at=NOW)
    session = FakeSession(
        scalars=[[order]],
        objects={(Diagnosis, diagnosis_id): diagnosis, (Approval, approval_id): approval},
    )
    response = _request("/api/v1/work-orders", session)

    assert response.status_code == 200
    body = response.json()[0]
    assert body["fault_type"] == "BEARING_WEAR"
    assert body["approval_actor"] == "operator-1"
    assert body["evidence_refs"] == ["ev-1"]
