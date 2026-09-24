"""Incident lifecycle command API and Incident Operations Center endpoints.

The five operator commands move an incident through its state machine. Every
route is a guarded transition through ``IncidentLifecycleService``; an illegal
move returns 409 with the legal targets named in the error payload.

Phase 6.9-C adds the read side of the Incident Operations Center (dashboard,
workflow bridge, operational metrics) and the one new write: starting the
existing decision workflow from an incident. The start route only gates and
delegates — the workflow engine's graph, policy, and approval flow are reused
untouched, and no work order is ever created on this path.

There is deliberately no incident creation endpoint here and no
alarm-to-incident entry point. Incidents are created by the existing operator
flow (``POST /incidents`` in the workflow API, from a diagnosis) and
internally by the correlation service.
"""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.core.context import trace_id_context
from app.core.errors import AppError
from app.incidents.contracts import (
    IncidentContextRead,
    IncidentDashboardItemRead,
    IncidentDashboardRead,
    IncidentDashboardSummaryRead,
    IncidentLifecycleAcknowledgeRead,
    IncidentLifecycleRead,
    IncidentMetricsRead,
    IncidentNoteRequest,
    IncidentWorkflowBridgeRead,
)
from app.incidents.incident_service import IncidentContextService, IncidentLifecycleService
from app.incidents.operations import IncidentOperationsService, IncidentWorkflowGate
from app.security.dependencies import require_permission
from app.security.rbac import (
    INCIDENT_ACK,
    INCIDENT_CLOSE,
    INCIDENT_INVESTIGATE,
    INCIDENT_READ,
    INCIDENT_REOPEN,
    INCIDENT_RESOLVE,
    WORKFLOW_START,
    Principal,
)
from app.workflow.contracts import WorkflowRead
from app.workflow.service import WorkflowService

router = APIRouter(prefix="/incidents", tags=["incidents"])

Session = Annotated[AsyncSession, Depends(get_session)]

#: Every route below declares its own permission. The dependency returns the
#: authenticated principal, so the lifecycle commands record the real identity
#: as the actor instead of a caller-supplied header.
ReadIncident = Annotated[Principal, Depends(require_permission(INCIDENT_READ))]


def _workflow_service(request: Request) -> WorkflowService:
    service = cast(WorkflowService | None, request.app.state.workflow_service)
    if service is None:
        raise AppError("WORKFLOW_NOT_AVAILABLE", "Workflow service is not available.", 503)
    return service


@router.get("/dashboard", response_model=IncidentDashboardRead)
async def incident_dashboard(
    session: Session,
    principal: ReadIncident,
    status: str | None = None,
    severity: str | None = None,
    device_id: str | None = None,
) -> IncidentDashboardRead:
    """Incident Operations Center payload: header counters plus the table.

    The counters describe the whole incident population; ``incidents`` is the
    newest page matching the filters. Read-only — nothing here mutates state.
    """

    summary, rows = await IncidentOperationsService(session).dashboard(
        status=status, severity=severity, device_id=device_id
    )
    return IncidentDashboardRead(
        summary=IncidentDashboardSummaryRead.model_validate(summary),
        incidents=[IncidentDashboardItemRead.model_validate(row) for row in rows],
    )


@router.get("/metrics", response_model=IncidentMetricsRead)
async def incident_metrics(session: Session, principal: ReadIncident) -> IncidentMetricsRead:
    """Operational metrics: MTTA, MTTR, and the alarm compression ratio."""

    return IncidentMetricsRead.model_validate(await IncidentOperationsService(session).metrics())


@router.get("/{incident_id}/workflow-context", response_model=IncidentWorkflowBridgeRead)
async def incident_workflow_context(
    incident_id: UUID, session: Session, principal: ReadIncident
) -> IncidentWorkflowBridgeRead:
    """Where this incident stands in the existing decision workflow.

    ``approval_required`` is true only while the latest run is actually waiting
    on a human decision. Read-only.
    """

    return IncidentWorkflowBridgeRead.model_validate(
        await IncidentOperationsService(session).workflow_context(incident_id)
    )


@router.post("/{incident_id}/start-workflow", response_model=WorkflowRead)
async def start_incident_workflow(
    incident_id: UUID,
    session: Session,
    request: Request,
    principal: Annotated[Principal, Depends(require_permission(WORKFLOW_START))],
) -> WorkflowRead:
    """Enter the existing decision workflow from the Incident Center.

    The gate refuses incidents whose status cannot legally reach the
    workflow-owned ``UNDER_ANALYSIS`` and incidents without a usable diagnosis
    (409 ``INCIDENT_NOT_READY``). On pass, the pre-existing
    ``WorkflowService.start`` creates the run — idempotently — and the graph
    runs exactly as it always has: triage, planning, safety review, then the
    human approval interrupt. No work order is created here and the approval
    flow cannot be bypassed from this endpoint.
    """

    gate = IncidentWorkflowGate(session)
    incident, diagnosis = await gate.ensure_ready(incident_id)
    gate.record_gate_pass(incident, diagnosis)
    await session.commit()
    service = _workflow_service(request)
    return await service.start(incident_id, diagnosis.id, trace_id_context.get())


@router.post("/{incident_id}/acknowledge", response_model=IncidentLifecycleAcknowledgeRead)
async def acknowledge_incident(
    incident_id: UUID,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(INCIDENT_ACK))],
    payload: IncidentNoteRequest | None = None,
) -> IncidentLifecycleAcknowledgeRead:
    """OPEN -> ACKNOWLEDGED. Records the actor and an optional note."""

    note = payload.note if payload is not None else None
    incident = await IncidentLifecycleService(session).acknowledge_incident(
        incident_id, actor=principal.username, note=note
    )
    result = IncidentLifecycleAcknowledgeRead.model_validate(incident)
    result.note = note
    return result


@router.post("/{incident_id}/investigate", response_model=IncidentLifecycleRead)
async def start_investigation(
    incident_id: UUID,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(INCIDENT_INVESTIGATE))],
) -> IncidentLifecycleRead:
    """ACKNOWLEDGED (or REOPENED) -> INVESTIGATING."""

    incident = await IncidentLifecycleService(session).start_investigation(
        incident_id, actor=principal.username
    )
    return IncidentLifecycleRead.model_validate(incident)


@router.post("/{incident_id}/resolve", response_model=IncidentLifecycleRead)
async def resolve_incident(
    incident_id: UUID,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(INCIDENT_RESOLVE))],
) -> IncidentLifecycleRead:
    """MITIGATED -> RESOLVED."""

    incident = await IncidentLifecycleService(session).resolve_incident(
        incident_id, actor=principal.username
    )
    return IncidentLifecycleRead.model_validate(incident)


@router.post("/{incident_id}/close", response_model=IncidentLifecycleRead)
async def close_incident(
    incident_id: UUID,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(INCIDENT_CLOSE))],
) -> IncidentLifecycleRead:
    """RESOLVED -> CLOSED."""

    incident = await IncidentLifecycleService(session).close_incident(
        incident_id, actor=principal.username
    )
    return IncidentLifecycleRead.model_validate(incident)


@router.post("/{incident_id}/reopen", response_model=IncidentLifecycleRead)
async def reopen_incident(
    incident_id: UUID,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(INCIDENT_REOPEN))],
) -> IncidentLifecycleRead:
    """CLOSED -> REOPENED."""

    incident = await IncidentLifecycleService(session).reopen_incident(
        incident_id, actor=principal.username
    )
    return IncidentLifecycleRead.model_validate(incident)


@router.get("/{incident_id}/context", response_model=IncidentContextRead)
async def get_incident_context(
    incident_id: UUID, session: Session, principal: ReadIncident
) -> IncidentContextRead:
    """Read-only bundle: incident, alarms, device, asset, diagnosis, audit timeline.

    This is the shape a later agent-facing phase will consume. Nothing here
    triggers an agent, a workflow, or any write.
    """

    return await IncidentContextService(session).build_context(incident_id)
