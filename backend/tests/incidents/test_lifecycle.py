"""Alarm instance lifecycle, deduplication, and correlation behaviour.

These tests run against real PostgreSQL because the properties under test are
database properties. "At most one open instance per device and rule" is a partial
unique index. "A recurrence after clearing opens a new instance" follows from that
index's predicate. A fake repository could be made to satisfy either statement
without the schema actually enforcing it.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents.correlation import (
    CorrelationWindowError,
    find_related_alarm,
    find_related_alarms,
    resolve_reference,
    window_start,
)
from app.incidents.errors import AlarmNotFoundError, AlarmStateError
from app.incidents.rules import RuleBreach
from app.incidents.service import AlarmLifecycleService
from app.models import Alarm, AuditEvent, Incident, IncidentAlarm, Telemetry
from app.repositories.alarm import AlarmRepository
from app.repositories.incident_alarm import IncidentAlarmRepository
from app.repositories.telemetry import TelemetryRepository
from app.schemas.telemetry import TelemetryIn
from tests.incidents.conftest import create_device, seed_rule, telemetry_payload, utc

DEVICE = "MOTOR-001"


def breach(
    *,
    rule_id: str = "temperature_high",
    severity: str = "CRITICAL",
    priority: str = "URGENT",
    observed: float = 95.0,
    threshold: float = 90.0,
    message: str = "95 °C > 90 °C",
) -> RuleBreach:
    return RuleBreach(
        rule_id=rule_id,
        rule_name=rule_id,
        signal_name="temperature",
        operator="GT",
        threshold=threshold,
        observed=observed,
        severity=severity,
        priority=priority,
        message=message,
    )


async def add_telemetry(session: AsyncSession, payload: dict[str, object]) -> Telemetry:
    """Persist one telemetry row so an alarm can reference a real measurement."""

    row = await TelemetryRepository(session).insert_once(TelemetryIn.model_validate(payload))
    assert row is not None
    return row


async def count_alarms(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(Alarm)) or 0)


async def test_one_sustained_condition_produces_one_instance(session: AsyncSession) -> None:
    """The central deduplication requirement.

    A thousand consecutive breaches used to be a thousand rows. They are now one
    instance whose occurrence count records the volume that the row count used to.
    """

    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    service = AlarmLifecycleService(session)
    first_moment = utc(2026, 9, 23, 10, 0, 0)
    created_ids = []

    for index in range(100):
        moment = first_moment + timedelta(seconds=index)
        row = await add_telemetry(
            session, telemetry_payload(DEVICE, timestamp=moment, temperature_c=95.0)
        )
        touched = await service.record_breaches(
            device_id=DEVICE,
            device_type="MOTOR",
            telemetry_id=row.id,
            payload=telemetry_payload(DEVICE, timestamp=moment, temperature_c=95.0),
        )
        assert len(touched) == 1
        created_ids.append(touched[0].id)

    await session.commit()

    assert await count_alarms(session) == 1
    assert len(set(created_ids)) == 1

    alarm = (await session.scalars(select(Alarm))).one()
    assert alarm.occurrence_count == 100
    assert alarm.status == "ACTIVE"
    assert alarm.started_at == first_moment
    assert alarm.last_triggered_at == first_moment + timedelta(seconds=99)


async def test_the_first_breach_keeps_the_instance_anchor(session: AsyncSession) -> None:
    """``started_at`` and ``telemetry_id`` still point at the first breach."""

    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    service = AlarmLifecycleService(session)
    first = await add_telemetry(
        session, telemetry_payload(DEVICE, timestamp=utc(2026, 9, 23, 10, 0, 0), temperature_c=95.0)
    )
    await service.record_breaches(
        device_id=DEVICE,
        device_type="MOTOR",
        telemetry_id=first.id,
        payload=telemetry_payload(DEVICE, temperature_c=95.0),
    )
    second = await add_telemetry(
        session, telemetry_payload(DEVICE, timestamp=utc(2026, 9, 23, 10, 5, 0), temperature_c=99.0)
    )
    await service.record_breaches(
        device_id=DEVICE,
        device_type="MOTOR",
        telemetry_id=second.id,
        payload=telemetry_payload(DEVICE, temperature_c=99.0),
    )
    await session.commit()

    alarm = (await session.scalars(select(Alarm))).one()
    assert alarm.telemetry_id == first.id
    assert alarm.started_at == utc(2026, 9, 23, 10, 0, 0)


async def test_a_late_sample_never_moves_last_triggered_at_backwards(session: AsyncSession) -> None:
    """Out-of-order telemetry must not make a live condition look stale."""

    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    service = AlarmLifecycleService(session)
    latest = utc(2026, 9, 23, 10, 10, 0)
    await service.create_or_update_alarm(
        device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=latest
    )
    await service.create_or_update_alarm(
        device_id=DEVICE,
        breach=breach(),
        telemetry_id=None,
        triggered_at=latest - timedelta(minutes=9),
    )
    await session.commit()

    alarm = (await session.scalars(select(Alarm))).one()
    assert alarm.last_triggered_at == latest
    assert alarm.started_at == latest
    assert alarm.occurrence_count == 2


async def test_lifecycle_moves_active_to_acknowledged_to_cleared(session: AsyncSession) -> None:
    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    service = AlarmLifecycleService(session)
    alarm, _ = await service.create_or_update_alarm(
        device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=utc()
    )
    await session.commit()
    assert alarm.status == "ACTIVE"
    assert alarm.acknowledged_at is None
    assert alarm.cleared_at is None

    acknowledged = await service.acknowledge_alarm(alarm.id, actor="operator.one", note="triaged")
    assert acknowledged.status == "ACKNOWLEDGED"
    assert acknowledged.acknowledged_at is not None
    assert acknowledged.acknowledged_by == "operator.one"
    assert acknowledged.cleared_at is None

    cleared = await service.clear_alarm(alarm.id, actor="operator.one", reason="cooled down")
    assert cleared.status == "CLEARED"
    assert cleared.cleared_at is not None
    assert cleared.clear_reason == "cooled down"


async def test_cleared_is_terminal_and_active_is_refused(session: AsyncSession) -> None:
    """The explicitly required illegal move."""

    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    service = AlarmLifecycleService(session)
    alarm, _ = await service.create_or_update_alarm(
        device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=utc()
    )
    await service.clear_alarm(alarm.id, actor="operator.one", reason="normal again")

    with pytest.raises(AlarmStateError) as raised:
        await service.clear_alarm(alarm.id, actor="operator.two", reason="clear it again")

    assert raised.value.code == "ALARM_STATE_INVALID"
    assert raised.value.details["current_status"] == "CLEARED"
    assert raised.value.details["target_status"] == "CLEARED"
    assert raised.value.details["allowed"] == []


async def test_acknowledging_a_cleared_instance_is_refused(session: AsyncSession) -> None:
    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    service = AlarmLifecycleService(session)
    alarm, _ = await service.create_or_update_alarm(
        device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=utc()
    )
    await service.clear_alarm(alarm.id, actor="operator.one", reason="normal again")

    with pytest.raises(AlarmStateError) as raised:
        await service.acknowledge_alarm(alarm.id, actor="operator.one")

    assert raised.value.details["target_status"] == "ACKNOWLEDGED"
    assert raised.value.details["allowed"] == []


async def test_a_repeat_acknowledgement_is_refused(session: AsyncSession) -> None:
    """The transition table is the contract, so a self move is not silently allowed."""

    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    service = AlarmLifecycleService(session)
    alarm, _ = await service.create_or_update_alarm(
        device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=utc()
    )
    await service.acknowledge_alarm(alarm.id, actor="operator.one")

    with pytest.raises(AlarmStateError) as raised:
        await service.acknowledge_alarm(alarm.id, actor="operator.one")

    assert raised.value.details["allowed"] == ["ACTIVE", "CLEARED"]


async def test_clearing_preserves_the_row_and_a_recurrence_opens_a_new_one(
    session: AsyncSession,
) -> None:
    """History is retained: the closed instance survives in full."""

    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    service = AlarmLifecycleService(session)
    first, _ = await service.create_or_update_alarm(
        device_id=DEVICE,
        breach=breach(),
        telemetry_id=None,
        triggered_at=utc(2026, 9, 23, 10, 0, 0),
    )
    await service.clear_alarm(first.id, actor="operator.one", reason="normal again")

    second, created = await service.create_or_update_alarm(
        device_id=DEVICE,
        breach=breach(),
        telemetry_id=None,
        triggered_at=utc(2026, 9, 23, 12, 0, 0),
    )
    await session.commit()

    assert created is True
    assert second.id != first.id
    assert await count_alarms(session) == 2

    rows = (await session.scalars(select(Alarm).order_by(Alarm.started_at))).all()
    assert [row.status for row in rows] == ["CLEARED", "ACTIVE"]
    assert rows[0].clear_reason == "normal again"
    assert rows[0].cleared_at is not None
    assert rows[0].occurrence_count == 1


async def test_an_acknowledged_instance_absorbs_further_breaches(session: AsyncSession) -> None:
    """Acknowledgement means seen, not resolved, so the condition keeps counting."""

    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    service = AlarmLifecycleService(session)
    alarm, _ = await service.create_or_update_alarm(
        device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=utc()
    )
    await service.acknowledge_alarm(alarm.id, actor="operator.one")

    again, created = await service.create_or_update_alarm(
        device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=utc()
    )
    await session.commit()

    assert created is False
    assert again.id == alarm.id
    assert again.status == "ACKNOWLEDGED"
    assert again.occurrence_count == 2
    assert await count_alarms(session) == 1


async def test_the_database_refuses_a_second_open_instance(session: AsyncSession) -> None:
    """The invariant is the index, not a service-layer convention."""

    from sqlalchemy.exc import IntegrityError

    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    repository = AlarmRepository(session)
    await repository.create(
        device_id=DEVICE,
        telemetry_id=None,
        rule_id="temperature_high",
        severity="CRITICAL",
        message="first",
        started_at=utc(2026, 9, 23, 10, 0, 0),
    )
    await session.commit()

    with pytest.raises(IntegrityError):
        await repository.create(
            device_id=DEVICE,
            telemetry_id=None,
            rule_id="temperature_high",
            severity="CRITICAL",
            message="second",
            started_at=utc(2026, 9, 23, 11, 0, 0),
        )
        await session.flush()
    await session.rollback()


async def test_a_cleared_row_frees_the_open_slot(session: AsyncSession) -> None:
    """The index predicate is what allows a recurrence to exist as a new row."""

    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    repository = AlarmRepository(session)
    for index in range(3):
        alarm = await repository.create(
            device_id=DEVICE,
            telemetry_id=None,
            rule_id="temperature_high",
            severity="CRITICAL",
            message=f"occurrence {index}",
            started_at=utc(2026, 9, 23, 10 + index, 0, 0),
        )
        alarm.status = "CLEARED"
        alarm.cleared_at = utc(2026, 9, 23, 10 + index, 30, 0)
        await session.flush()
    await session.commit()

    assert await count_alarms(session) == 3
    assert await repository.find_open(DEVICE, "temperature_high") is None


async def test_the_race_between_two_workers_resolves_to_an_update(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two ingest workers can both miss the lookup and both attempt the insert.

    The partial unique index refuses the second insert. The correct outcome is the
    update branch, and the session has to remain usable afterwards so the telemetry
    row in the same transaction still commits.
    """

    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    service = AlarmLifecycleService(session)
    first, _ = await service.create_or_update_alarm(
        device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=utc()
    )
    await session.commit()

    real_find_open = AlarmRepository.find_open
    calls = {"count": 0}

    async def flaky_find_open(self: AlarmRepository, device_id: str, rule_id: str) -> Alarm | None:
        calls["count"] += 1
        if calls["count"] == 1:
            return None
        return await real_find_open(self, device_id, rule_id)

    monkeypatch.setattr(AlarmRepository, "find_open", flaky_find_open)

    recovered, created = await service.create_or_update_alarm(
        device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=utc()
    )
    await session.commit()

    assert calls["count"] >= 2
    assert created is False
    assert recovered.id == first.id
    assert await count_alarms(session) == 1
    assert recovered.occurrence_count == 2


async def test_a_disabled_rule_produces_no_alarm(session: AsyncSession) -> None:
    await create_device(session, DEVICE)
    await seed_rule(session, enabled=False)
    await session.commit()

    service = AlarmLifecycleService(session)
    touched = await service.record_breaches(
        device_id=DEVICE,
        device_type="MOTOR",
        telemetry_id=None,
        payload=telemetry_payload(DEVICE, temperature_c=200.0),
    )
    await session.commit()

    assert touched == []
    assert await count_alarms(session) == 0


async def test_a_rule_scoped_to_another_device_type_produces_no_alarm(
    session: AsyncSession,
) -> None:
    await create_device(session, DEVICE, device_type="MOTOR")
    await seed_rule(session, device_type="PUMP")
    await session.commit()

    service = AlarmLifecycleService(session)
    touched = await service.record_breaches(
        device_id=DEVICE,
        device_type="MOTOR",
        telemetry_id=None,
        payload=telemetry_payload(DEVICE, temperature_c=200.0),
    )
    await session.commit()

    assert touched == []


async def test_a_live_condition_stays_active_when_the_signal_returns_to_normal(
    session: AsyncSession,
) -> None:
    """Documents a deliberate deferral rather than a defect.

    Phase 6.9-A implements operator clearing only. Automatic clearing on
    normalization needs hysteresis and a sustained-normal duration, which belong
    to the correlation stage. Until then a condition that has recovered remains
    ACTIVE and visible until a person closes it, which is the safe direction.
    """

    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    service = AlarmLifecycleService(session)
    await service.create_or_update_alarm(
        device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=utc()
    )
    touched = await service.record_breaches(
        device_id=DEVICE,
        device_type="MOTOR",
        telemetry_id=None,
        payload=telemetry_payload(DEVICE, temperature_c=20.0),
    )
    await session.commit()

    assert touched == []
    alarm = (await session.scalars(select(Alarm))).one()
    assert alarm.status == "ACTIVE"
    assert alarm.cleared_at is None


async def test_the_two_seeded_thresholds_behave_as_they_did_before(session: AsyncSession) -> None:
    """The rules are data now, and the data reproduces the replaced literals."""

    await create_device(session, DEVICE)
    await seed_rule(
        session,
        "HIGH_TEMPERATURE",
        signal_name="temperature",
        threshold=90.0,
        severity="CRITICAL",
    )
    await seed_rule(
        session,
        "HIGH_VIBRATION",
        signal_name="vibration",
        threshold=7.0,
        severity="WARNING",
        priority="HIGH",
    )
    await session.commit()

    service = AlarmLifecycleService(session)

    at_limit = await service.record_breaches(
        device_id=DEVICE,
        device_type="MOTOR",
        telemetry_id=None,
        payload=telemetry_payload(DEVICE, temperature_c=90.0, vibration_mm_s=7.0),
    )
    assert at_limit == []

    above = await service.record_breaches(
        device_id=DEVICE,
        device_type="MOTOR",
        telemetry_id=None,
        payload=telemetry_payload(DEVICE, temperature_c=90.1, vibration_mm_s=7.1),
    )
    await session.commit()

    assert sorted(alarm.rule_id for alarm in above) == ["HIGH_TEMPERATURE", "HIGH_VIBRATION"]
    severities = {alarm.rule_id: alarm.severity for alarm in above}
    assert severities == {"HIGH_TEMPERATURE": "CRITICAL", "HIGH_VIBRATION": "WARNING"}


async def test_audit_records_state_changes_and_not_activity_volume(session: AsyncSession) -> None:
    """One audit row per state change, zero per repeated breach."""

    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    service = AlarmLifecycleService(session)
    alarm, _ = await service.create_or_update_alarm(
        device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=utc()
    )
    for _ in range(9):
        await service.create_or_update_alarm(
            device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=utc()
        )
    await service.acknowledge_alarm(alarm.id, actor="operator.one", note="seen")
    await service.clear_alarm(alarm.id, actor="operator.one", reason="cooled down")
    await session.commit()

    actions = (
        await session.scalars(select(AuditEvent.action).order_by(AuditEvent.timestamp))
    ).all()
    assert list(actions) == ["ALARM_CREATED", "ALARM_ACKNOWLEDGED", "ALARM_CLEARED"]

    cleared = (
        await session.scalars(select(AuditEvent).where(AuditEvent.action == "ALARM_CLEARED"))
    ).one()
    assert cleared.actor == "operator.one"
    assert cleared.details["reason"] == "cooled down"
    assert cleared.details["previous_status"] == "ACKNOWLEDGED"
    assert cleared.details["occurrence_count"] == 10


async def test_the_creation_audit_record_names_the_rule_and_the_breach(
    session: AsyncSession,
) -> None:
    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    service = AlarmLifecycleService(session)
    await service.create_or_update_alarm(
        device_id=DEVICE, breach=breach(observed=95.5, threshold=90.0), telemetry_id=None
    )
    await session.commit()

    created = (
        await session.scalars(select(AuditEvent).where(AuditEvent.action == "ALARM_CREATED"))
    ).one()
    assert created.resource == DEVICE
    assert created.details["rule_id"] == "temperature_high"
    assert created.details["observed"] == 95.5
    assert created.details["threshold"] == 90.0


async def test_acknowledging_an_unknown_alarm_is_a_not_found(session: AsyncSession) -> None:
    await create_device(session, DEVICE)
    await session.commit()

    with pytest.raises(AlarmNotFoundError) as raised:
        await AlarmLifecycleService(session).acknowledge_alarm(uuid4(), actor="operator.one")

    assert raised.value.code == "ALARM_NOT_FOUND"


async def test_an_unrecognised_stored_status_is_refused(session: AsyncSession) -> None:
    """Defence in depth for a value the check constraint already prevents."""

    await create_device(session, DEVICE)
    await seed_rule(session)
    await session.commit()

    service = AlarmLifecycleService(session)
    alarm, _ = await service.create_or_update_alarm(
        device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=utc()
    )
    await session.commit()

    alarm.status = "SUPERSEDED"
    with pytest.raises(AlarmStateError) as raised:
        await service.acknowledge_alarm(alarm.id, actor="operator.one")
    assert raised.value.details["current_status"] == "SUPERSEDED"


class TestCorrelation:
    """The correlation foundation answers questions and acts on none of them."""

    async def test_an_open_instance_is_found_regardless_of_age(self, session: AsyncSession) -> None:
        await create_device(session, DEVICE)
        await seed_rule(session)
        await session.commit()

        service = AlarmLifecycleService(session)
        opened = utc(2026, 9, 23, 1, 0, 0)
        alarm, _ = await service.create_or_update_alarm(
            device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=opened
        )
        await session.commit()

        found = await find_related_alarm(
            session,
            device_id=DEVICE,
            rule_id="temperature_high",
            window_seconds=60,
            reference=opened + timedelta(hours=9),
        )
        assert found is not None
        assert found.id == alarm.id

    async def test_a_cleared_instance_is_found_inside_the_window(
        self, session: AsyncSession
    ) -> None:
        await create_device(session, DEVICE)
        await seed_rule(session)
        await session.commit()

        service = AlarmLifecycleService(session)
        closed_at = utc(2026, 9, 23, 10, 0, 0)
        alarm, _ = await service.create_or_update_alarm(
            device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=closed_at
        )
        await service.clear_alarm(alarm.id, actor="operator.one", reason="normal again")
        await session.commit()

        found = await find_related_alarm(
            session,
            device_id=DEVICE,
            rule_id="temperature_high",
            window_seconds=300,
            reference=closed_at + timedelta(seconds=120),
        )
        assert found is not None
        assert found.id == alarm.id

    async def test_a_cleared_instance_outside_the_window_is_not_related(
        self, session: AsyncSession
    ) -> None:
        await create_device(session, DEVICE)
        await seed_rule(session)
        await session.commit()

        service = AlarmLifecycleService(session)
        closed_at = utc(2026, 9, 23, 10, 0, 0)
        alarm, _ = await service.create_or_update_alarm(
            device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=closed_at
        )
        await service.clear_alarm(alarm.id, actor="operator.one", reason="normal again")
        await session.commit()

        found = await find_related_alarm(
            session,
            device_id=DEVICE,
            rule_id="temperature_high",
            window_seconds=60,
            reference=closed_at + timedelta(hours=2),
        )
        assert found is None

    async def test_an_open_instance_wins_over_a_cleared_one(self, session: AsyncSession) -> None:
        await create_device(session, DEVICE)
        await seed_rule(session)
        await session.commit()

        service = AlarmLifecycleService(session)
        older, _ = await service.create_or_update_alarm(
            device_id=DEVICE,
            breach=breach(),
            telemetry_id=None,
            triggered_at=utc(2026, 9, 23, 9, 0),
        )
        await service.clear_alarm(older.id, actor="operator.one", reason="normal again")
        current, _ = await service.create_or_update_alarm(
            device_id=DEVICE,
            breach=breach(),
            telemetry_id=None,
            triggered_at=utc(2026, 9, 23, 10, 0),
        )
        await session.commit()

        found = await find_related_alarm(
            session,
            device_id=DEVICE,
            rule_id="temperature_high",
            window_seconds=60,
            reference=utc(2026, 9, 23, 10, 0),
        )
        assert found is not None
        assert found.id == current.id

    async def test_related_alarms_can_be_restricted_to_recent_activity(
        self, session: AsyncSession
    ) -> None:
        await create_device(session, DEVICE)
        await seed_rule(session)
        await session.commit()

        service = AlarmLifecycleService(session)
        await service.create_or_update_alarm(
            device_id=DEVICE,
            breach=breach(),
            telemetry_id=None,
            triggered_at=utc(2026, 9, 23, 10, 0),
        )
        await session.commit()

        reference = utc(2026, 9, 23, 10, 1)
        live = await find_related_alarms(
            session, device_id=DEVICE, window_seconds=300, reference=reference
        )
        assert len(live) == 1

        # The instance's activity (10:00) falls inside the window [09:56, 10:01],
        # so a recent-activity-restricted lookup still sees it.
        historical = await find_related_alarms(
            session,
            device_id=DEVICE,
            window_seconds=300,
            reference=reference,
            include_open=False,
        )
        assert [alarm.id for alarm in historical] == [live[0].id]

        # Move the window past the last activity. The open instance still
        # qualifies by being open, but the activity-restricted lookup does not.
        later = utc(2026, 9, 23, 11, 0)
        still_live = await find_related_alarms(
            session, device_id=DEVICE, window_seconds=300, reference=later
        )
        assert len(still_live) == 1
        stale = await find_related_alarms(
            session,
            device_id=DEVICE,
            window_seconds=300,
            reference=later,
            include_open=False,
        )
        assert stale == []

    async def test_a_device_with_no_alarms_has_nothing_related(self, session: AsyncSession) -> None:
        await create_device(session, DEVICE)
        await seed_rule(session)
        await session.commit()

        assert (
            await find_related_alarm(
                session, device_id=DEVICE, rule_id="temperature_high", window_seconds=300
            )
            is None
        )

    def test_the_window_is_validated(self) -> None:
        with pytest.raises(CorrelationWindowError):
            window_start(utc(), 0)
        with pytest.raises(CorrelationWindowError):
            window_start(utc(), 86_401)

    def test_a_naive_reference_is_refused(self) -> None:
        from datetime import datetime

        with pytest.raises(CorrelationWindowError):
            resolve_reference(datetime(2026, 9, 23, 10, 0, 0))


class TestIncidentLinkage:
    """The relation exists and nothing fills it automatically."""

    async def test_linking_an_alarm_to_an_incident_is_idempotent(
        self, session: AsyncSession
    ) -> None:
        await create_device(session, DEVICE)
        await seed_rule(session)
        incident = Incident(device_id=DEVICE, title="Bearing wear", status="OPEN", priority="HIGH")
        session.add(incident)
        await session.flush()
        alarm, _ = await AlarmLifecycleService(session).create_or_update_alarm(
            device_id=DEVICE, breach=breach(), telemetry_id=None, triggered_at=utc()
        )
        await session.commit()

        repository = IncidentAlarmRepository(session)
        first = await repository.link(incident.id, alarm.id)
        second = await repository.link(incident.id, alarm.id)
        await session.commit()

        assert first is not None
        assert second is None
        assert int(await session.scalar(select(func.count()).select_from(IncidentAlarm)) or 0) == 1
        assert await repository.incident_ids_for_alarm(alarm.id) == [incident.id]
        assert await repository.alarm_ids_for_incident(incident.id) == [alarm.id]

    async def test_no_incident_is_created_by_the_alarm_path(self, session: AsyncSession) -> None:
        """There is no automatic alarm to incident link in this phase."""

        await create_device(session, DEVICE)
        await seed_rule(session)
        await session.commit()

        await AlarmLifecycleService(session).record_breaches(
            device_id=DEVICE,
            device_type="MOTOR",
            telemetry_id=None,
            payload=telemetry_payload(DEVICE, temperature_c=200.0),
        )
        await session.commit()

        assert int(await session.scalar(select(func.count()).select_from(Incident)) or 0) == 0
        assert int(await session.scalar(select(func.count()).select_from(IncidentAlarm)) or 0) == 0
