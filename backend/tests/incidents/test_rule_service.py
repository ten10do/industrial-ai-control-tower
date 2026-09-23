"""Alarm rule registry persistence: creation, disabling, and rejection.

The rule registry is what makes a threshold change a data change. These tests
cover the write path, including the two cases the phase brief calls out: creating
a rule, disabling one, and rejecting an unusable threshold.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents.contracts import AlarmRuleCreate, AlarmRuleUpdate
from app.incidents.errors import (
    AlarmRuleConflictError,
    AlarmRuleNotFoundError,
    AlarmRuleValidationError,
)
from app.incidents.service import AlarmRuleService
from app.models import AuditEvent


def create_payload(**overrides: object) -> AlarmRuleCreate:
    values: dict[str, object] = {
        "id": "bearing_temperature_high",
        "name": "High bearing temperature",
        "description": "Bearing housing above the warning band.",
        "device_type": None,
        "signal_name": "bearing_temperature",
        "operator": "GT",
        "threshold": 85.0,
        "severity": "MAJOR",
        "priority": "HIGH",
        "enabled": True,
    }
    values.update(overrides)
    return AlarmRuleCreate.model_validate(values)


async def test_a_rule_can_be_created(session: AsyncSession) -> None:
    service = AlarmRuleService(session)
    rule = await service.create_rule(create_payload(), actor="engineer.one")

    assert rule.id == "bearing_temperature_high"
    assert rule.signal_name == "bearing_temperature"
    assert rule.operator == "GT"
    assert rule.threshold == 85.0
    assert rule.severity == "MAJOR"
    assert rule.priority == "HIGH"
    assert rule.enabled is True
    assert rule.created_at is not None
    assert rule.updated_at is not None


async def test_creating_a_rule_writes_one_audit_record(session: AsyncSession) -> None:
    await AlarmRuleService(session).create_rule(create_payload(), actor="engineer.one")

    audit = (
        await session.scalars(select(AuditEvent).where(AuditEvent.action == "ALARM_RULE_CREATED"))
    ).one()
    assert audit.actor == "engineer.one"
    assert audit.resource == "bearing_temperature_high"
    assert audit.details["threshold"] == 85.0
    assert audit.details["enabled"] is True


async def test_a_duplicate_rule_id_is_a_conflict(session: AsyncSession) -> None:
    service = AlarmRuleService(session)
    await service.create_rule(create_payload())

    with pytest.raises(AlarmRuleConflictError) as raised:
        await service.create_rule(create_payload(name="A second definition"))

    assert raised.value.code == "ALARM_RULE_CONFLICT"
    assert raised.value.status_code == 409


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"threshold": float("nan")}, "THRESHOLD_NOT_FINITE"),
        ({"threshold": float("inf")}, "THRESHOLD_NOT_FINITE"),
        ({"threshold": 5_000.0}, "THRESHOLD_OUT_OF_RANGE"),
        ({"threshold": -5_000.0}, "THRESHOLD_OUT_OF_RANGE"),
        ({"signal_name": "torque"}, "SIGNAL_UNKNOWN"),
        ({"operator": "APPROX"}, "OPERATOR_UNKNOWN"),
        ({"severity": "CATASTROPHIC"}, "SEVERITY_UNKNOWN"),
        ({"priority": "WHENEVER"}, "PRIORITY_UNKNOWN"),
        ({"id": "bad id"}, "RULE_ID_INVALID"),
        ({"name": ""}, "NAME_REQUIRED"),
    ],
)
async def test_an_unusable_rule_is_rejected_and_never_stored(
    session: AsyncSession, overrides: dict[str, object], code: str
) -> None:
    service = AlarmRuleService(session)

    with pytest.raises((AlarmRuleValidationError, PydanticValidationError)) as raised:
        await service.create_rule(create_payload(**overrides))

    # An empty name is refused by the request contract itself before the service
    # validator runs, so the stable code is only observable for the other cases.
    error = raised.value
    if isinstance(error, AlarmRuleValidationError):
        assert error.code == "ALARM_RULE_INVALID"
        assert error.status_code == 422
        assert [issue["code"] for issue in error.errors] == [code]
    assert await service.list_rules() == []


async def test_an_out_of_range_threshold_reports_the_permitted_range(session: AsyncSession) -> None:
    with pytest.raises(AlarmRuleValidationError) as raised:
        await AlarmRuleService(session).create_rule(
            create_payload(signal_name="temperature", threshold=900.0)
        )

    message = raised.value.errors[0]["message"]
    assert "-50" in message
    assert "250" in message


async def test_a_rule_can_be_disabled(session: AsyncSession) -> None:
    """Disabling retires a rule without deleting the history that names it."""

    service = AlarmRuleService(session)
    await service.create_rule(create_payload())

    updated = await service.update_rule(
        "bearing_temperature_high", AlarmRuleUpdate(enabled=False), actor="engineer.two"
    )

    assert updated.enabled is False
    assert updated.threshold == 85.0
    assert updated.signal_name == "bearing_temperature"


async def test_a_patch_leaves_unmentioned_fields_untouched(session: AsyncSession) -> None:
    service = AlarmRuleService(session)
    await service.create_rule(create_payload(device_type="PUMP"))

    updated = await service.update_rule("bearing_temperature_high", AlarmRuleUpdate(threshold=88.0))

    assert updated.threshold == 88.0
    assert updated.device_type == "PUMP"
    assert updated.name == "High bearing temperature"
    assert updated.enabled is True


async def test_a_patch_can_widen_a_rule_to_every_device_type(session: AsyncSession) -> None:
    """An explicit null is meaningful and must not be treated as an absent field."""

    service = AlarmRuleService(session)
    await service.create_rule(create_payload(device_type="PUMP"))

    updated = await service.update_rule(
        "bearing_temperature_high", AlarmRuleUpdate(device_type=None)
    )

    assert updated.device_type is None


async def test_a_patch_records_only_the_changed_fields(session: AsyncSession) -> None:
    service = AlarmRuleService(session)
    await service.create_rule(create_payload())

    await service.update_rule(
        "bearing_temperature_high", AlarmRuleUpdate(threshold=88.0, severity="CRITICAL")
    )

    audit = (
        await session.scalars(select(AuditEvent).where(AuditEvent.action == "ALARM_RULE_UPDATED"))
    ).one()
    assert audit.details["changed_fields"] == ["severity", "threshold"]


async def test_an_empty_patch_is_refused(session: AsyncSession) -> None:
    service = AlarmRuleService(session)
    await service.create_rule(create_payload())

    with pytest.raises(AlarmRuleValidationError) as raised:
        await service.update_rule("bearing_temperature_high", AlarmRuleUpdate())

    assert raised.value.errors[0]["code"] == "NO_FIELDS"


async def test_a_patch_that_would_make_the_rule_unusable_is_refused(session: AsyncSession) -> None:
    service = AlarmRuleService(session)
    await service.create_rule(create_payload())

    with pytest.raises(AlarmRuleValidationError) as raised:
        await service.update_rule("bearing_temperature_high", AlarmRuleUpdate(threshold=9_000.0))

    assert raised.value.errors[0]["code"] == "THRESHOLD_OUT_OF_RANGE"
    rule = await service.get_rule("bearing_temperature_high")
    assert rule.threshold == 85.0


async def test_patching_an_unknown_rule_is_a_not_found(session: AsyncSession) -> None:
    with pytest.raises(AlarmRuleNotFoundError) as raised:
        await AlarmRuleService(session).update_rule("nope", AlarmRuleUpdate(enabled=False))

    assert raised.value.code == "ALARM_RULE_NOT_FOUND"


async def test_listing_can_be_restricted_to_enabled_rules(session: AsyncSession) -> None:
    service = AlarmRuleService(session)
    await service.create_rule(create_payload())
    await service.create_rule(create_payload(id="other_rule", name="Other rule", enabled=False))

    assert len(await service.list_rules()) == 2
    enabled = await service.list_rules(enabled_only=True)
    assert [rule.id for rule in enabled] == ["bearing_temperature_high"]


async def test_applicable_rules_include_global_and_matching_scoped_rules(
    session: AsyncSession,
) -> None:
    service = AlarmRuleService(session)
    await service.create_rule(create_payload(id="global_rule", name="Global", device_type=None))
    await service.create_rule(create_payload(id="pump_rule", name="Pump", device_type="PUMP"))
    await service.create_rule(create_payload(id="motor_rule", name="Motor", device_type="MOTOR"))

    applicable = await service.applicable_rules("MOTOR")
    assert sorted(rule.id for rule in applicable) == ["global_rule", "motor_rule"]

    unknown_type = await service.applicable_rules(None)
    assert [rule.id for rule in unknown_type] == ["global_rule"]


async def test_a_disabled_scoped_rule_is_not_applicable(session: AsyncSession) -> None:
    service = AlarmRuleService(session)
    await service.create_rule(create_payload(id="global_rule", name="Global", enabled=False))

    assert await service.applicable_rules("MOTOR") == []
