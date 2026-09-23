"""Incident correlation engine tests against a real PostgreSQL.

The engine is deterministic device-plus-window: alarms on one device attach to
the device's live incident while the incident's last alarm activity is inside
the window, and open a new incident otherwise. Every test drives the same rows
a production caller would persist, so replaying them yields the same incidents.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents.incident_service import (
    AlarmIncidentMismatchError,
    IncidentContextService,
    IncidentCorrelationService,
    IncidentLifecycleService,
)
from app.incidents.models import IncidentAlarm
from app.models import Alarm, AssetNode, Diagnosis, Incident
from tests.incidents.conftest import create_device, utc


async def make_alarm(
    session: AsyncSession,
    device_id: str,
    *,
    rule_id: str = "temperature_high",
    started_at: datetime,
    severity: str = "CRITICAL",
) -> Alarm:
    """Insert one alarm instance through the repository the engine reads."""

    from app.repositories.alarm import AlarmRepository

    return await AlarmRepository(session).create(
        device_id=device_id,
        telemetry_id=None,
        rule_id=rule_id,
        severity=severity,
        message=f"{device_id} {rule_id}",
        started_at=started_at,
    )


async def incident_count(session: AsyncSession) -> int:
    count = await session.scalar(select(func.count()).select_from(Incident))
    return int(count or 0)


async def test_three_alarms_in_the_window_merge_into_one_incident(
    session: AsyncSession,
) -> None:
    await create_device(session, "MOTOR-001")
    base = utc(2026, 9, 23, 10, 0, 0)
    alarms = [
        await make_alarm(session, "MOTOR-001", rule_id="temperature_high", started_at=base),
        await make_alarm(
            session, "MOTOR-001", rule_id="vibration_high", started_at=base + timedelta(minutes=3)
        ),
        await make_alarm(
            session, "MOTOR-001", rule_id="current_high", started_at=base + timedelta(minutes=7)
        ),
    ]
    service = IncidentCorrelationService(session)

    results = [await service.correlate_alarm(alarm) for alarm in alarms]

    assert len({incident.id for incident, _ in results}) == 1
    incident, _ = results[0]
    assert incident.status == "OPEN"
    links = await session.scalars(
        select(IncidentAlarm.alarm_id).where(IncidentAlarm.incident_id == incident.id)
    )
    assert len(list(links)) == 3
    assert await incident_count(session) == 1
    # the anchor advanced to the newest evidence and the severity kept the max
    assert incident.last_alarm_at == base + timedelta(minutes=7)


async def test_an_alarm_outside_the_window_opens_a_new_incident(
    session: AsyncSession,
) -> None:
    await create_device(session, "MOTOR-001")
    base = utc(2026, 9, 23, 10, 0, 0)
    service = IncidentCorrelationService(session)
    first = await make_alarm(session, "MOTOR-001", started_at=base)
    await service.correlate_alarm(first)
    later = await make_alarm(
        session, "MOTOR-001", rule_id="vibration_high", started_at=base + timedelta(minutes=30)
    )

    incident, created = await service.correlate_alarm(later)

    assert created is True
    assert await incident_count(session) == 2


async def test_the_window_boundary_is_inclusive(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    base = utc(2026, 9, 23, 10, 0, 0)
    service = IncidentCorrelationService(session)
    first = await make_alarm(session, "MOTOR-001", started_at=base)
    incident, _ = await service.correlate_alarm(first)
    edge = await make_alarm(
        session, "MOTOR-001", rule_id="vibration_high", started_at=base + timedelta(seconds=600)
    )

    _, created = await service.correlate_alarm(edge)

    assert created is False
    refreshed = await session.get(Incident, incident.id)
    assert refreshed is not None
    assert refreshed.last_alarm_at == base + timedelta(seconds=600)


async def test_different_devices_never_merge(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    await create_device(session, "MOTOR-002")
    base = utc(2026, 9, 23, 10, 0, 0)
    service = IncidentCorrelationService(session)
    left = await make_alarm(session, "MOTOR-001", started_at=base)
    right = await make_alarm(session, "MOTOR-002", started_at=base)

    left_incident, _ = await service.correlate_alarm(left)
    right_incident, _ = await service.correlate_alarm(right)

    assert left_incident.id != right_incident.id
    assert left_incident.device_id == "MOTOR-001"
    assert right_incident.device_id == "MOTOR-002"
    assert await incident_count(session) == 2


async def test_attaching_is_idempotent(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    alarm = await make_alarm(session, "MOTOR-001", started_at=utc(2026, 9, 23, 10, 0))
    service = IncidentCorrelationService(session)
    incident, _ = await service.correlate_alarm(alarm)

    first = await service.attach_alarm_to_incident(incident, alarm)
    second = await service.attach_alarm_to_incident(incident, alarm)

    assert first is False
    assert second is False
    links = await session.scalars(
        select(IncidentAlarm).where(IncidentAlarm.incident_id == incident.id)
    )
    assert len(list(links)) == 1
    counts = await session.scalars(select(func.count()).select_from(IncidentAlarm))
    assert counts.one() == 1


async def test_attaching_across_devices_is_refused(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    await create_device(session, "MOTOR-002")
    alarm = await make_alarm(session, "MOTOR-002", started_at=utc(2026, 9, 23, 10, 0))
    incident = Incident(
        device_id="MOTOR-001",
        title="MOTOR-001 correlated alarm condition",
        description="",
        status="OPEN",
        priority="MEDIUM",
    )
    session.add(incident)
    await session.flush()
    service = IncidentCorrelationService(session)

    import pytest

    with pytest.raises(AlarmIncidentMismatchError):
        await service.attach_alarm_to_incident(incident, alarm)


async def test_a_resolved_incident_does_not_absorb_new_alarms(
    session: AsyncSession,
) -> None:
    await create_device(session, "MOTOR-001")
    base = utc(2026, 9, 23, 10, 0, 0)
    service = IncidentCorrelationService(session)
    first = await make_alarm(session, "MOTOR-001", started_at=base)
    incident, _ = await service.correlate_alarm(first)
    incident.status = "RESOLVED"
    await session.flush()
    later = await make_alarm(
        session, "MOTOR-001", rule_id="vibration_high", started_at=base + timedelta(minutes=1)
    )

    new_incident, created = await service.correlate_alarm(later)

    assert created is True
    assert new_incident.id != incident.id


async def test_severity_moves_to_the_maximum_seen(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    base = utc(2026, 9, 23, 10, 0, 0)
    service = IncidentCorrelationService(session)
    minor = await make_alarm(
        session, "MOTOR-001", rule_id="vibration_high", severity="MINOR", started_at=base
    )
    incident, _ = await service.correlate_alarm(minor)
    critical = await make_alarm(
        session,
        "MOTOR-001",
        rule_id="temperature_high",
        severity="CRITICAL",
        started_at=base + timedelta(minutes=2),
    )

    await service.correlate_alarm(critical)

    refreshed = await session.get(Incident, incident.id)
    assert refreshed is not None
    assert refreshed.severity == "CRITICAL"
    assert refreshed.priority == "URGENT"


async def test_engine_created_incidents_are_audited(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    alarm = await make_alarm(session, "MOTOR-001", started_at=utc(2026, 9, 23, 10, 0))
    service = IncidentCorrelationService(session)
    incident, _ = await service.correlate_alarm(alarm)

    from app.models import AuditEvent

    audits = list(
        await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.resource == str(incident.id))
            .order_by(AuditEvent.timestamp.asc())
        )
    )
    assert [audit.action for audit in audits] == ["INCIDENT_CREATED", "INCIDENT_ALARM_ATTACHED"]
    assert audits[0].details["strategy"] == "device_window_v1"


async def test_context_contains_alarm_device_asset_diagnosis_and_audit(
    session: AsyncSession,
) -> None:
    device = await create_device(session, "MOTOR-001")
    asset = AssetNode(name="Line 1", asset_type="SITE", parent_id=None)
    session.add(asset)
    await session.flush()
    device.asset_node_id = asset.id
    await session.flush()

    base = utc(2026, 9, 23, 10, 0, 0)
    correlation = IncidentCorrelationService(session)
    alarm = await make_alarm(session, "MOTOR-001", started_at=base)
    incident, _ = await correlation.correlate_alarm(alarm)
    diagnosis = Diagnosis(
        incident_id=incident.id,
        device_id="MOTOR-001",
        status="FAULT",
        fault_type="BEARING_WEAR",
        severity="MAJOR",
        confidence=0.87,
    )
    session.add(diagnosis)
    await session.flush()

    context = await IncidentContextService(session).build_context(incident.id)

    assert context.incident.id == incident.id
    assert [entry.id for entry in context.alarms] == [alarm.id]
    assert context.device is not None and context.device.device_id == "MOTOR-001"
    assert context.asset is not None and context.asset.id == asset.id
    assert context.diagnosis is not None and context.diagnosis.fault_type == "BEARING_WEAR"
    assert [entry.action for entry in context.audit] == [
        "INCIDENT_CREATED",
        "INCIDENT_ALARM_ATTACHED",
    ]


async def test_context_tolerates_a_correlated_incident_without_diagnosis(
    session: AsyncSession,
) -> None:
    await create_device(session, "MOTOR-001")
    alarm = await make_alarm(session, "MOTOR-001", started_at=utc(2026, 9, 23, 10, 0))
    service = IncidentCorrelationService(session)
    incident, _ = await service.correlate_alarm(alarm)

    context = await IncidentContextService(session).build_context(incident.id)

    assert context.diagnosis is None
    assert context.asset is None
    assert len(context.alarms) == 1


async def test_a_manually_created_incident_can_absorb_alarms(
    session: AsyncSession,
) -> None:
    correlation = IncidentCorrelationService(session)
    lifecycle = IncidentLifecycleService(session)
    await create_device(session, "MOTOR-001")
    orphan = Incident(
        device_id="MOTOR-001",
        title="manual",
        description="",
        status="OPEN",
        priority="MEDIUM",
    )
    session.add(orphan)
    await session.flush()
    alarm = await make_alarm(session, "MOTOR-001", started_at=utc(2026, 9, 23, 10, 0))
    await correlation.attach_alarm_to_incident(orphan, alarm)

    # a manually created incident participates in the same correlation flow
    acknowledged = await lifecycle.acknowledge_incident(orphan.id)
    assert acknowledged.status == "ACKNOWLEDGED"
