"""Alarm instance API: reading, operator acknowledgement, and operator clearing.

An alarm here is an active condition instance, not a rule trigger record. The
list endpoint therefore answers "what is currently wrong on this device, and for
how long" rather than "how many samples breached a threshold".

The acknowledge and clear endpoints are the only alarm mutations. Both are
guarded state moves driven by the alarm transition table, and both record the
caller-supplied actor label from the ``X-Actor`` header. Neither can reach a
device.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_actor, get_session
from app.core.errors import AppError
from app.incidents.contracts import (
    AlarmAcknowledgeRequest,
    AlarmClearRequest,
    AlarmDetailRead,
    AlarmRead,
)
from app.incidents.correlation import (
    DEFAULT_WINDOW_SECONDS,
    MAX_WINDOW_SECONDS,
    find_related_alarms,
)
from app.incidents.service import AlarmLifecycleService
from app.repositories.alarm import AlarmRepository
from app.repositories.incident_alarm import IncidentAlarmRepository

router = APIRouter(prefix="/alarms", tags=["alarms"])

Actor = Annotated[str, Depends(get_actor)]
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[AlarmRead])
async def list_alarms(
    session: Session,
    device_id: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    rule_id: str | None = None,
    since: datetime | None = None,
    active_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AlarmRead]:
    """List alarm instances, newest first.

    ``active_only`` is shorthand for every status except ``CLEARED``. Passing it
    together with an explicit ``status`` is refused rather than silently resolved
    one way, because the two would contradict each other.
    """

    if active_only and status is not None:
        raise AppError(
            "ALARM_FILTER_CONFLICT",
            "active_only and status cannot be combined; use one or the other.",
            422,
        )
    alarms = await AlarmRepository(session).list_instances(
        device_id,
        limit,
        status=status,
        severity=severity,
        rule_id=rule_id,
        since=since,
        open_only=active_only,
    )
    return [AlarmRead.model_validate(alarm) for alarm in alarms]


# Declared before the ``/{alarm_id}`` route on purpose. FastAPI matches path
# operations in declaration order, so ``/alarms/related`` has to be registered
# before ``/alarms/{alarm_id}`` or the literal segment would be parsed as an id.
@router.get("/related", response_model=list[AlarmRead])
async def list_related_alarms(
    session: Session,
    device_id: str,
    rule_id: str | None = None,
    window_seconds: Annotated[int, Query(ge=1, le=MAX_WINDOW_SECONDS)] = DEFAULT_WINDOW_SECONDS,
    since: datetime | None = None,
    include_open: Annotated[bool, Query()] = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AlarmRead]:
    """List the alarm instances related to a device inside a time window.

    This is the correlation foundation exposed read-only. It answers "which
    conditions on this device belong to the same period" and it deliberately does
    nothing with the answer. Assembling an incident from these alarms is the next
    phase.
    """

    alarms = await find_related_alarms(
        session,
        device_id=device_id,
        window_seconds=window_seconds,
        reference=since,
        rule_id=rule_id,
        include_open=include_open,
        limit=limit,
    )
    return [AlarmRead.model_validate(alarm) for alarm in alarms]


@router.get("/{alarm_id}", response_model=AlarmDetailRead)
async def get_alarm(alarm_id: UUID, session: Session) -> AlarmDetailRead:
    """Return one alarm instance with the incidents it has been linked to."""

    alarm = await AlarmRepository(session).get(alarm_id)
    if alarm is None:
        raise AppError("ALARM_NOT_FOUND", f"Alarm {alarm_id} was not found.", 404)
    incident_ids = await IncidentAlarmRepository(session).incident_ids_for_alarm(alarm_id)
    detail = AlarmDetailRead.model_validate(alarm)
    return detail.model_copy(update={"incident_ids": incident_ids})


@router.post("/{alarm_id}/acknowledge", response_model=AlarmRead)
async def acknowledge_alarm(
    alarm_id: UUID,
    payload: AlarmAcknowledgeRequest,
    session: Session,
    actor: Actor,
) -> AlarmRead:
    """Record that an operator has seen the condition."""

    alarm = await AlarmLifecycleService(session).acknowledge_alarm(
        alarm_id, actor=actor, note=payload.note
    )
    return AlarmRead.model_validate(alarm)


@router.post("/{alarm_id}/clear", response_model=AlarmRead)
async def clear_alarm(
    alarm_id: UUID,
    payload: AlarmClearRequest,
    session: Session,
    actor: Actor,
) -> AlarmRead:
    """Close the instance. A recurrence afterwards opens a new one."""

    alarm = await AlarmLifecycleService(session).clear_alarm(
        alarm_id, actor=actor, reason=payload.reason
    )
    return AlarmRead.model_validate(alarm)
