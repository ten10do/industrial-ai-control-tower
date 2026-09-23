"""Incident lifecycle command API.

The five operator commands move an incident through its state machine. Every
route is a guarded transition through ``IncidentLifecycleService``; an illegal
move returns 409 with the legal targets named in the error payload.

There is deliberately no creation endpoint here and no alarm-to-incident entry
point. Incidents are created by the existing operator flow (``POST /incidents``
in the workflow API, from a diagnosis) and internally by the correlation
service; exposing an automatic creation route would let callers bypass the
deterministic strategy, and that boundary belongs to a later phase.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_actor, get_session
from app.incidents.contracts import (
    IncidentContextRead,
    IncidentLifecycleAcknowledgeRead,
    IncidentLifecycleRead,
    IncidentNoteRequest,
)
from app.incidents.incident_service import IncidentContextService, IncidentLifecycleService

router = APIRouter(prefix="/incidents", tags=["incidents"])

Actor = Annotated[str, Depends(get_actor)]
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/{incident_id}/acknowledge", response_model=IncidentLifecycleAcknowledgeRead)
async def acknowledge_incident(
    incident_id: UUID,
    session: Session,
    actor: Actor,
    payload: IncidentNoteRequest | None = None,
) -> IncidentLifecycleAcknowledgeRead:
    """OPEN -> ACKNOWLEDGED. Records the actor and an optional note."""

    note = payload.note if payload is not None else None
    incident = await IncidentLifecycleService(session).acknowledge_incident(
        incident_id, actor=actor, note=note
    )
    result = IncidentLifecycleAcknowledgeRead.model_validate(incident)
    result.note = note
    return result


@router.post("/{incident_id}/investigate", response_model=IncidentLifecycleRead)
async def start_investigation(
    incident_id: UUID, session: Session, actor: Actor
) -> IncidentLifecycleRead:
    """ACKNOWLEDGED (or REOPENED) -> INVESTIGATING."""

    incident = await IncidentLifecycleService(session).start_investigation(incident_id, actor=actor)
    return IncidentLifecycleRead.model_validate(incident)


@router.post("/{incident_id}/resolve", response_model=IncidentLifecycleRead)
async def resolve_incident(
    incident_id: UUID, session: Session, actor: Actor
) -> IncidentLifecycleRead:
    """MITIGATED -> RESOLVED."""

    incident = await IncidentLifecycleService(session).resolve_incident(incident_id, actor=actor)
    return IncidentLifecycleRead.model_validate(incident)


@router.post("/{incident_id}/close", response_model=IncidentLifecycleRead)
async def close_incident(
    incident_id: UUID, session: Session, actor: Actor
) -> IncidentLifecycleRead:
    """RESOLVED -> CLOSED."""

    incident = await IncidentLifecycleService(session).close_incident(incident_id, actor=actor)
    return IncidentLifecycleRead.model_validate(incident)


@router.post("/{incident_id}/reopen", response_model=IncidentLifecycleRead)
async def reopen_incident(
    incident_id: UUID, session: Session, actor: Actor
) -> IncidentLifecycleRead:
    """CLOSED -> REOPENED."""

    incident = await IncidentLifecycleService(session).reopen_incident(incident_id, actor=actor)
    return IncidentLifecycleRead.model_validate(incident)


@router.get("/{incident_id}/context", response_model=IncidentContextRead)
async def get_incident_context(incident_id: UUID, session: Session) -> IncidentContextRead:
    """Read-only bundle: incident, alarms, device, asset, diagnosis, audit timeline.

    This is the shape a later agent-facing phase will consume. Nothing here
    triggers an agent, a workflow, or any write.
    """

    return await IncidentContextService(session).build_context(incident_id)
