"""Phase 5 incident, workflow, approval, trace, cancellation, and work-order APIs."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.core.context import trace_id_context
from app.core.errors import AppError
from app.incidents.contracts import (
    AlarmRead,
    AssetContextRead,
    AuditEntryRead,
    DeviceContextRead,
)
from app.incidents.incident_service import IncidentContextService
from app.models import Approval, Diagnosis, Incident, WorkflowRun, WorkOrder
from app.workflow.contracts import (
    ApprovalDecisionRequest,
    ApprovalRead,
    IncidentCreateRequest,
    IncidentDetailContextRead,
    IncidentRead,
    IncidentSummaryRead,
    WorkflowCreateRequest,
    WorkflowRead,
    WorkflowStatus,
    WorkflowSummaryRead,
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


def _workflow_summary(row: WorkflowRun) -> WorkflowSummaryRead:
    return WorkflowSummaryRead(
        workflow_run_id=row.id,
        incident_id=row.incident_id,
        diagnosis_id=row.diagnosis_id,
        device_id=row.device_id,
        status=WorkflowStatus(row.status),
        current_stage=row.current_stage,
        policy_version=row.policy_version,
        provider=row.provider,
        model=row.model,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _incident_summary(
    session: AsyncSession, incident: Incident, diagnosis: Diagnosis | None = None
) -> IncidentSummaryRead:
    if diagnosis is None:
        diagnosis = await session.scalar(
            select(Diagnosis)
            .where(Diagnosis.incident_id == incident.id)
            .order_by(Diagnosis.created_at.desc())
            .limit(1)
        )
    if incident.device_id is None:
        raise AppError("INCIDENT_DATA_INCOMPLETE", "Incident has no device.", 409)
    workflow = await session.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.incident_id == incident.id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(1)
    )
    work_order = await session.scalar(
        select(WorkOrder).where(WorkOrder.incident_id == incident.id).limit(1)
    )
    return IncidentSummaryRead(
        incident_id=incident.id,
        device_id=incident.device_id,
        diagnosis_id=diagnosis.id,
        title=incident.title,
        status=incident.status,
        priority=incident.priority,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        diagnosis_status=diagnosis.status,
        fault_type=diagnosis.fault_type,
        severity=diagnosis.severity,
        workflow_run_id=workflow.id if workflow else None,
        workflow_status=workflow.status if workflow else None,
        work_order_id=work_order.id if work_order else None,
    )


async def _work_order_read(session: AsyncSession, row: WorkOrder) -> WorkOrderRead:
    assert row.workflow_run_id and row.device_id and row.incident_id and row.diagnosis_id
    assert row.title and row.priority
    diagnosis = await session.get(Diagnosis, row.diagnosis_id)
    approval = await session.get(Approval, row.approval_id) if row.approval_id else None
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
        fault_type=diagnosis.fault_type if diagnosis else None,
        approval_actor=approval.actor if approval else None,
        approval_decided_at=approval.decided_at if approval else None,
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


@router.get("/incidents", response_model=list[IncidentSummaryRead])
async def list_incidents(
    session: Annotated[AsyncSession, Depends(get_session)],
    status: str | None = None,
    severity: str | None = None,
    device_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[IncidentSummaryRead]:
    statement = select(Incident).order_by(Incident.created_at.desc()).limit(limit)
    if status:
        statement = statement.where(Incident.status == status)
    if severity:
        statement = statement.where(Incident.severity == severity)
    if device_id:
        statement = statement.where(Incident.device_id == device_id)
    incidents = list(await session.scalars(statement))
    return [await _incident_summary(session, incident) for incident in incidents]


@router.get("/incidents/{incident_id}", response_model=IncidentDetailContextRead)
async def get_incident(
    incident_id: UUID, session: Annotated[AsyncSession, Depends(get_session)]
) -> IncidentDetailContextRead:
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise AppError("INCIDENT_NOT_FOUND", "Incident was not found.", 404)
    diagnosis = await session.scalar(
        select(Diagnosis)
        .where(Diagnosis.incident_id == incident_id)
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )
    summary = await _incident_summary(session, incident, diagnosis)
    context = IncidentContextService(session)
    alarms = await context.linked_alarms(incident_id)
    device, asset = await context.device_with_asset(incident)
    timeline = await context.audit_timeline(incident_id)
    latest_workflow = await session.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.incident_id == incident_id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(1)
    )
    return IncidentDetailContextRead(
        **summary.model_dump(),
        description=incident.description,
        diagnosis={
            "id": str(diagnosis.id),
            "device_id": diagnosis.device_id,
            "window_start": diagnosis.window_start,
            "window_end": diagnosis.window_end,
            "status": diagnosis.status,
            "fault_type": diagnosis.fault_type,
            "anomaly_score": diagnosis.anomaly_score,
            "confidence": diagnosis.confidence,
            "severity": diagnosis.severity,
            "evidence": diagnosis.evidence,
            "model_version": diagnosis.model_version,
            "feature_version": diagnosis.feature_version,
            "trace_id": diagnosis.trace_id,
            "created_at": diagnosis.created_at,
        }
        if diagnosis is not None
        else {},
        alarms=[AlarmRead.model_validate(alarm) for alarm in alarms],
        device=DeviceContextRead.model_validate(device) if device else None,
        asset=AssetContextRead.model_validate(asset) if asset else None,
        audit=[AuditEntryRead.model_validate(entry) for entry in timeline],
        workflow=_workflow_summary(latest_workflow) if latest_workflow is not None else None,
    )


@router.post("/incidents/{incident_id}/workflows", response_model=WorkflowRead)
async def start_workflow(
    request: Request, incident_id: UUID, payload: WorkflowCreateRequest
) -> WorkflowRead:
    return await _service(request).start(incident_id, payload.diagnosis_id, trace_id_context.get())


@router.get("/workflow-metrics", response_model=dict[str, int | float])
async def workflow_metrics(request: Request) -> dict[str, int | float]:
    return await _service(request).metrics()


@router.get("/workflows", response_model=list[WorkflowSummaryRead])
async def list_workflows(
    session: Annotated[AsyncSession, Depends(get_session)],
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[WorkflowSummaryRead]:
    statement = select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(limit)
    if status:
        statement = statement.where(WorkflowRun.status == status)
    rows = list(await session.scalars(statement))
    return [_workflow_summary(row) for row in rows]


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
    return await _work_order_read(session, row)


@router.get("/work-orders", response_model=list[WorkOrderRead])
async def list_work_orders(
    session: Annotated[AsyncSession, Depends(get_session)],
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[WorkOrderRead]:
    statement = select(WorkOrder).order_by(WorkOrder.created_at.desc()).limit(limit)
    if status:
        statement = statement.where(WorkOrder.status == status)
    rows = list(await session.scalars(statement))
    return [await _work_order_read(session, row) for row in rows]
