"""Phase 5 incident, workflow, approval, trace, cancellation, and work-order APIs."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.core.context import trace_id_context
from app.core.errors import AppError
from app.models import Approval, Diagnosis, Incident, WorkOrder
from app.workflow.contracts import (
    ApprovalDecisionRequest,
    ApprovalRead,
    IncidentCreateRequest,
    IncidentRead,
    WorkflowCreateRequest,
    WorkflowRead,
    WorkflowTrace,
    WorkOrderRead,
)
from app.workflow.service import WorkflowService

router = APIRouter(prefix="/api/v1", tags=["workflows"])


def _service(request: Request) -> WorkflowService:
    service = cast(WorkflowService | None, request.app.state.workflow_service)
    if service is None:
        raise AppError("WORKFLOW_NOT_AVAILABLE", "Workflow service is not available.", 503)
    return service


def _approval_read(row: Approval) -> ApprovalRead:
    assert row.workflow_run_id and row.maintenance_plan_id and row.plan_hash
    return ApprovalRead(
        approval_id=row.id,
        workflow_run_id=row.workflow_run_id,
        maintenance_plan_id=row.maintenance_plan_id,
        status=row.decision,
        actor=row.actor,
        reason=row.reason,
        plan_version=row.plan_version,
        plan_hash=row.plan_hash,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


@router.post("/incidents", response_model=IncidentRead, status_code=201)
async def create_incident(
    payload: IncidentCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IncidentRead:
    diagnosis = await session.get(Diagnosis, payload.diagnosis_id)
    if diagnosis is None or diagnosis.device_id != payload.device_id:
        raise AppError(
            "INVALID_INCIDENT_INPUT", "Diagnosis does not belong to the requested device.", 422
        )
    if diagnosis.incident_id is not None:
        incident = await session.get(Incident, diagnosis.incident_id)
        assert incident is not None
    else:
        incident = Incident(
            device_id=payload.device_id,
            title=payload.title,
            description=payload.description,
            priority=payload.priority,
            status="OPEN",
        )
        session.add(incident)
        await session.flush()
        diagnosis.incident_id = incident.id
        await session.commit()
    return IncidentRead(
        incident_id=incident.id,
        device_id=payload.device_id,
        diagnosis_id=diagnosis.id,
        title=incident.title,
        status=incident.status,
        priority=incident.priority,
    )


@router.post("/incidents/{incident_id}/workflows", response_model=WorkflowRead)
async def start_workflow(
    request: Request, incident_id: UUID, payload: WorkflowCreateRequest
) -> WorkflowRead:
    return await _service(request).start(incident_id, payload.diagnosis_id, trace_id_context.get())


@router.get("/workflow-metrics", response_model=dict[str, int | float])
async def workflow_metrics(request: Request) -> dict[str, int | float]:
    return await _service(request).metrics()


@router.get("/workflows/{workflow_run_id}", response_model=WorkflowRead)
async def get_workflow(request: Request, workflow_run_id: UUID) -> WorkflowRead:
    return await _service(request).get(workflow_run_id)


@router.get("/workflows/{workflow_run_id}/trace", response_model=WorkflowTrace)
async def get_workflow_trace(request: Request, workflow_run_id: UUID) -> WorkflowTrace:
    workflow, runs = await _service(request).trace(workflow_run_id)
    return WorkflowTrace(workflow=workflow, agent_runs=runs)


@router.post("/workflows/{workflow_run_id}/cancel", response_model=WorkflowRead)
async def cancel_workflow(request: Request, workflow_run_id: UUID) -> WorkflowRead:
    return await _service(request).cancel(workflow_run_id)


@router.get("/approvals/pending", response_model=list[ApprovalRead])
async def pending_approvals(request: Request) -> list[ApprovalRead]:
    return [_approval_read(row) for row in await _service(request).pending_approvals()]


@router.get("/approvals/{approval_id}", response_model=ApprovalRead)
async def get_approval(request: Request, approval_id: UUID) -> ApprovalRead:
    return _approval_read(await _service(request).get_approval(approval_id))


async def _decide(
    request: Request,
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    actor: str | None,
    decision: str,
) -> WorkflowRead:
    if actor is None or not actor.strip():
        raise AppError(
            "ACTOR_REQUIRED",
            "X-Development-Actor is required for Phase 5 approval audit.",
            422,
        )
    return await _service(request).decide_approval(
        approval_id, decision=decision, actor=actor.strip(), reason=payload.reason
    )


@router.post("/approvals/{approval_id}/approve", response_model=WorkflowRead)
async def approve(
    request: Request,
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    actor: Annotated[str | None, Header(alias="X-Development-Actor")] = None,
) -> WorkflowRead:
    return await _decide(request, approval_id, payload, actor, "APPROVED")


@router.post("/approvals/{approval_id}/reject", response_model=WorkflowRead)
async def reject(
    request: Request,
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    actor: Annotated[str | None, Header(alias="X-Development-Actor")] = None,
) -> WorkflowRead:
    return await _decide(request, approval_id, payload, actor, "REJECTED")


@router.get("/work-orders/{work_order_id}", response_model=WorkOrderRead)
async def get_work_order(
    work_order_id: UUID, session: Annotated[AsyncSession, Depends(get_session)]
) -> WorkOrderRead:
    row = await session.get(WorkOrder, work_order_id)
    if row is None:
        raise AppError("WORK_ORDER_NOT_FOUND", "Work order was not found.", 404)
    assert row.workflow_run_id and row.device_id and row.incident_id and row.diagnosis_id
    assert row.title and row.priority
    return WorkOrderRead(
        work_order_id=row.id,
        workflow_run_id=row.workflow_run_id,
        device_id=row.device_id,
        incident_id=row.incident_id,
        diagnosis_id=row.diagnosis_id,
        title=row.title,
        priority=row.priority,
        plan=row.plan,
        evidence_refs=row.evidence_refs,
        safety_requirements=row.safety_requirements,
        approval_id=row.approval_id,
        status=row.status,
        created_at=row.created_at,
    )
