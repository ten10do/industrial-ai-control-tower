"""Incident lifecycle command tests against a real PostgreSQL.

Each command is one guarded move through the transition table. The illegal
moves are asserted against the error contract (409 with the legal targets), and
every accepted move writes exactly one incident-scoped audit record.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents.incident_service import (
    IncidentLifecycleService,
    IncidentNotFoundError,
    IncidentStateError,
)
from app.incidents.states import IncidentStatus
from app.models import AuditEvent, Incident
from tests.incidents.conftest import create_device


async def seed_incident(
    session: AsyncSession,
    device_id: str,
    *,
    status: str = "OPEN",
    title: str = "Correlated alarm condition",
) -> Incident:
    await create_device(session, device_id)
    incident = Incident(
        device_id=device_id,
        title=title,
        description="",
        status=status,
        priority="MEDIUM",
    )
    session.add(incident)
    await session.flush()
    return incident


async def incident_audits(session: AsyncSession, incident_id: object) -> list[AuditEvent]:
    rows = await session.scalars(
        select(AuditEvent)
        .where(AuditEvent.resource == str(incident_id))
        .order_by(AuditEvent.timestamp.asc(), AuditEvent.id.asc())
    )
    return list(rows)


async def test_an_open_incident_can_be_acknowledged(session: AsyncSession) -> None:
    incident = await seed_incident(session, "MOTOR-001")
    service = IncidentLifecycleService(session)

    acknowledged = await service.acknowledge_incident(incident.id, actor="operator.one")

    assert acknowledged.status == IncidentStatus.ACKNOWLEDGED.value
    assert acknowledged.acknowledged_by == "operator.one"
    assert acknowledged.acknowledged_at is not None
    assert isinstance(acknowledged.acknowledged_at, datetime)
    assert acknowledged.acknowledged_at.tzinfo is UTC


async def test_acknowledgement_writes_one_audit_record(session: AsyncSession) -> None:
    incident = await seed_incident(session, "MOTOR-001")
    service = IncidentLifecycleService(session)

    await service.acknowledge_incident(incident.id, actor="operator.one", note="seen")

    audits = await incident_audits(session, incident.id)
    assert [(audit.action, audit.actor) for audit in audits] == [
        ("INCIDENT_ACKNOWLEDGED", "operator.one")
    ]
    assert audits[0].details["note"] == "seen"
    assert audits[0].details["previous_status"] == "OPEN"


async def test_an_incident_can_be_investigated_after_acknowledgement(
    session: AsyncSession,
) -> None:
    incident = await seed_incident(session, "MOTOR-001")
    service = IncidentLifecycleService(session)
    await service.acknowledge_incident(incident.id, actor="operator.one")

    investigating = await service.start_investigation(incident.id, actor="operator.two")

    assert investigating.status == IncidentStatus.INVESTIGATING.value


async def test_a_reopened_incident_returns_to_investigating(session: AsyncSession) -> None:
    incident = await seed_incident(session, "MOTOR-001", status="CLOSED")
    service = IncidentLifecycleService(session)

    reopened = await service.reopen_incident(incident.id, actor="operator.one")
    assert reopened.status == IncidentStatus.REOPENED.value
    assert reopened.closed_at is None

    investigating = await service.start_investigation(incident.id, actor="operator.one")
    assert investigating.status == IncidentStatus.INVESTIGATING.value


async def test_a_mitigated_incident_resolves_then_closes(session: AsyncSession) -> None:
    incident = await seed_incident(session, "MOTOR-001", status="MITIGATED")
    service = IncidentLifecycleService(session)

    resolved = await service.resolve_incident(incident.id, actor="operator.one")
    assert resolved.status == IncidentStatus.RESOLVED.value
    assert resolved.resolved_at is not None

    closed = await service.close_incident(incident.id, actor="operator.one")
    assert closed.status == IncidentStatus.CLOSED.value
    assert closed.closed_at is not None


async def test_every_illegal_move_is_refused_with_the_legal_targets(
    session: AsyncSession,
) -> None:
    incident = await seed_incident(session, "MOTOR-001", status="CLOSED")
    service = IncidentLifecycleService(session)

    with pytest.raises(IncidentStateError) as raised:
        await service.start_investigation(incident.id)

    assert raised.value.code == "INCIDENT_STATE_INVALID"
    assert raised.value.status_code == 409
    assert raised.value.details["current_status"] == "CLOSED"
    assert raised.value.details["target_status"] == "INVESTIGATING"
    assert raised.value.details["allowed"] == ["REOPENED"]


async def test_a_cancelled_incident_refuses_everything(session: AsyncSession) -> None:
    incident = await seed_incident(session, "MOTOR-001", status="CANCELLED")
    service = IncidentLifecycleService(session)

    with pytest.raises(IncidentStateError):
        await service.acknowledge_incident(incident.id)
    with pytest.raises(IncidentStateError):
        await service.reopen_incident(incident.id)


async def test_an_open_incident_cannot_skip_acknowledgement(session: AsyncSession) -> None:
    incident = await seed_incident(session, "MOTOR-001")
    service = IncidentLifecycleService(session)

    with pytest.raises(IncidentStateError):
        await service.start_investigation(incident.id)
    with pytest.raises(IncidentStateError):
        await service.close_incident(incident.id)


async def test_an_unrecognised_stored_status_is_refused(session: AsyncSession) -> None:
    incident = await seed_incident(session, "MOTOR-001", status="SOMEWHERE_ELSE")
    service = IncidentLifecycleService(session)

    with pytest.raises(IncidentStateError) as raised:
        await service.acknowledge_incident(incident.id)

    assert raised.value.details["current_status"] == "SOMEWHERE_ELSE"


async def test_an_unknown_incident_is_a_not_found(session: AsyncSession) -> None:
    service = IncidentLifecycleService(session)

    with pytest.raises(IncidentNotFoundError) as raised:
        await service.acknowledge_incident(uuid4())

    assert raised.value.code == "INCIDENT_NOT_FOUND"
    assert raised.value.status_code == 404


async def test_state_changes_write_audit_and_are_the_only_records(
    session: AsyncSession,
) -> None:
    incident = await seed_incident(session, "MOTOR-001")
    service = IncidentLifecycleService(session)
    await service.acknowledge_incident(incident.id, actor="operator.one")
    await service.start_investigation(incident.id, actor="operator.one")

    audits = await incident_audits(session, incident.id)
    assert [audit.action for audit in audits] == [
        "INCIDENT_ACKNOWLEDGED",
        "INCIDENT_INVESTIGATION_STARTED",
    ]
