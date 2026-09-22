"""Configuration lifecycle: draft, validate, publish, archive, rollback.

These tests run against real PostgreSQL because most of what this phase promises is
enforced by the database: version uniqueness, the single-published partial unique
index, the status check constraints, and the published_at invariant. A fake
repository would prove none of that.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assetconfig.audit import (
    APPLY_FAILED,
    APPLY_SUCCEEDED,
    ARCHIVED,
    DRAFT_CREATED,
    DRAFT_DELETED,
    DRAFT_UPDATED,
    PUBLISHED,
    ROLLBACK_DRAFT_CREATED,
    VALIDATED,
)
from app.assetconfig.errors import (
    ApplyUnavailableError,
    ConfigurationImmutableError,
    ConfigurationNotFoundError,
    ConfigurationStateError,
    ConfigurationValidationError,
    DeviceNotFoundError,
)
from app.assetconfig.models import ConfigurationStatus, DeviceConfiguration
from app.assetconfig.service import ConfigurationService
from tests.assetconfig.conftest import (
    BlockingApplier,
    FakeApplier,
    create_device,
    modbus_payload,
    opcua_payload,
)


async def _service(
    session: AsyncSession, applier: FakeApplier | None = None
) -> ConfigurationService:
    return ConfigurationService(session, applier or FakeApplier())


async def test_create_draft_starts_at_version_one(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    draft = await service.create_draft("MOTOR-001", modbus_payload(), "alice")
    assert draft.version == 1
    assert draft.status == ConfigurationStatus.DRAFT.value
    assert draft.protocol == "modbus_tcp"
    assert draft.created_by == "alice"
    assert draft.published_at is None
    assert draft.configuration["device_id"] == "MOTOR-001"


async def test_versions_increment_per_device(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    await create_device(session, "MOTOR-002")
    service = await _service(session)
    first = await service.create_draft("MOTOR-001", modbus_payload("MOTOR-001"), "tester")
    second = await service.create_draft("MOTOR-001", modbus_payload("MOTOR-001"), "tester")
    other_device = await service.create_draft("MOTOR-002", modbus_payload("MOTOR-002"), "tester")
    # Version numbering is per device, not global.
    assert (first.version, second.version) == (1, 2)
    assert other_device.version == 1


async def test_create_draft_rejects_an_unknown_device(session: AsyncSession) -> None:
    service = await _service(session)
    with pytest.raises(DeviceNotFoundError):
        await service.create_draft("MOTOR-404", modbus_payload("MOTOR-404"), "tester")


async def test_create_draft_rejects_an_invalid_payload(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    payload = modbus_payload()
    payload["modbus_tcp"]["registers"] = {
        "temperature": {"address": 40001, "scale": 1.0, "unit": None}
    }
    service = await _service(session)
    with pytest.raises(ConfigurationValidationError):
        await service.create_draft("MOTOR-001", payload, "tester")


async def test_nothing_is_stored_when_a_payload_is_invalid(session: AsyncSession) -> None:
    """JSONB is not an excuse to skip the typed validator."""

    await create_device(session, "MOTOR-001")
    payload = modbus_payload()
    del payload["modbus_tcp"]["registers"]["power"]
    service = await _service(session)
    with pytest.raises(ConfigurationValidationError):
        await service.create_draft("MOTOR-001", payload, "tester")
    total = await session.scalar(select(func.count()).select_from(DeviceConfiguration))
    assert total == 0


async def test_update_draft_changes_the_snapshot(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    draft = await service.create_draft("MOTOR-001", modbus_payload(port=5020), "tester")
    updated = await service.update_draft(
        "MOTOR-001", draft.version, modbus_payload(port=5021), "tester"
    )
    assert updated.configuration["modbus_tcp"]["port"] == 5021
    assert updated.status == ConfigurationStatus.DRAFT.value


async def test_update_resets_a_validated_draft_to_draft(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    draft = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    await service.validate_version("MOTOR-001", draft.version)
    validated = await service.get_configuration("MOTOR-001", draft.version)
    assert validated.status == ConfigurationStatus.VALIDATED.value

    updated = await service.update_draft(
        "MOTOR-001", draft.version, modbus_payload(port=5022), "tester"
    )
    assert updated.status == ConfigurationStatus.DRAFT.value
    assert updated.validated_at is None
    assert updated.validation_result == {}


async def test_validate_passes_and_promotes_to_validated(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    draft = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    result = await service.validate_version("MOTOR-001", draft.version)
    assert result["valid"] is True
    assert result["errors"] == []


async def test_validate_fails_when_the_device_is_not_active(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001", status="DECOMMISSIONED")
    service = await _service(session)
    draft = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    result = await service.validate_version("MOTOR-001", draft.version)
    assert result["valid"] is False
    assert any(issue["code"] == "DEVICE_NOT_ACTIVE" for issue in result["errors"])
    row = await service.get_configuration("MOTOR-001", draft.version)
    assert row.status == ConfigurationStatus.DRAFT.value
    assert row.validation_error


async def test_publish_marks_the_version_published(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    applier = FakeApplier()
    service = await _service(session, applier)
    draft = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    row, status = await service.publish("MOTOR-001", draft.version, "tester")
    assert row.status == ConfigurationStatus.PUBLISHED.value
    assert row.published_at is not None
    assert status["desired_version"] == 1
    assert status["applied_version"] == 1
    assert status["apply_status"] == "APPLIED"
    assert status["source"] == "database"
    assert status["in_sync"] is True
    assert applier.calls == [("MOTOR-001", 1)]


async def test_publish_requires_a_valid_draft(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001", status="INACTIVE")
    service = await _service(session)
    draft = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    with pytest.raises(ConfigurationValidationError) as excinfo:
        await service.publish("MOTOR-001", draft.version, "tester")
    assert excinfo.value.details["errors"]
    row = await service.get_configuration("MOTOR-001", draft.version)
    assert row.status == ConfigurationStatus.DRAFT.value
    assert row.published_at is None


async def test_published_version_is_immutable(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    draft = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    await service.publish("MOTOR-001", draft.version, "tester")

    with pytest.raises(ConfigurationImmutableError):
        await service.update_draft("MOTOR-001", draft.version, modbus_payload(port=5999), "tester")
    with pytest.raises(ConfigurationStateError):
        await service.delete_draft("MOTOR-001", draft.version)

    unchanged = await service.get_configuration("MOTOR-001", draft.version)
    assert unchanged.configuration["modbus_tcp"]["port"] == 5020
    assert unchanged.status == ConfigurationStatus.PUBLISHED.value


async def test_publishing_a_new_version_archives_the_previous_one(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    v1 = await service.create_draft("MOTOR-001", modbus_payload(port=5020), "tester")
    await service.publish("MOTOR-001", v1.version, "tester")
    v2 = await service.create_draft("MOTOR-001", modbus_payload(port=5021), "tester")
    row, status = await service.publish("MOTOR-001", v2.version, "tester")

    assert row.version == 2
    previous = await service.get_configuration("MOTOR-001", 1)
    assert previous.status == ConfigurationStatus.ARCHIVED.value
    assert previous.archived_at is not None
    assert previous.published_at is not None
    assert status["desired_version"] == 2
    assert status["applied_version"] == 2


async def test_only_one_published_version_per_device(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    v1 = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    await service.publish("MOTOR-001", v1.version, "tester")
    v2 = await service.create_draft("MOTOR-001", modbus_payload(port=5021), "tester")
    await service.publish("MOTOR-001", v2.version, "tester")

    published = await session.scalars(
        select(DeviceConfiguration).where(
            DeviceConfiguration.device_id == "MOTOR-001",
            DeviceConfiguration.status == ConfigurationStatus.PUBLISHED.value,
        )
    )
    assert len(list(published)) == 1


async def test_database_refuses_a_second_published_row(session: AsyncSession) -> None:
    """The single-published rule is a database constraint, not only service logic."""

    await create_device(session, "MOTOR-001")
    service = await _service(session)
    v1 = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    await service.publish("MOTOR-001", v1.version, "tester")
    await session.commit()

    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO device_configurations (id, device_id, version, status, protocol, "
                "configuration, created_by, validation_result, created_at, updated_at, "
                "published_at) "
                "VALUES (gen_random_uuid(), 'MOTOR-001', 99, 'PUBLISHED', 'modbus_tcp', "
                "'{}'::jsonb, 'rogue', '{}'::jsonb, now(), now(), now())"
            )
        )
        await session.flush()


async def test_database_refuses_a_duplicate_version(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    await session.commit()

    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO device_configurations (id, device_id, version, status, protocol, "
                "configuration, created_by, validation_result, created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'MOTOR-001', 1, 'DRAFT', 'modbus_tcp', "
                "'{}'::jsonb, 'rogue', '{}'::jsonb, now(), now())"
            )
        )
        await session.flush()


async def test_database_refuses_an_unknown_status(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    await session.commit()
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO device_configurations (id, device_id, version, status, protocol, "
                "configuration, created_by, validation_result, created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'MOTOR-001', 5, 'PENDING', 'modbus_tcp', "
                "'{}'::jsonb, 'rogue', '{}'::jsonb, now(), now())"
            )
        )
        await session.flush()


async def test_database_refuses_published_without_a_timestamp(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    await session.commit()
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO device_configurations (id, device_id, version, status, protocol, "
                "configuration, created_by, validation_result, created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'MOTOR-001', 6, 'PUBLISHED', 'modbus_tcp', "
                "'{}'::jsonb, 'rogue', '{}'::jsonb, now(), now())"
            )
        )
        await session.flush()


async def test_history_is_preserved_newest_first(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    v1 = await service.create_draft("MOTOR-001", modbus_payload(port=5020), "tester")
    await service.publish("MOTOR-001", v1.version, "tester")
    v2 = await service.create_draft("MOTOR-001", modbus_payload(port=5021), "tester")
    await service.publish("MOTOR-001", v2.version, "tester")
    await service.create_draft("MOTOR-001", modbus_payload(port=5022), "tester")

    history = await service.list_configurations("MOTOR-001")
    assert [(row.version, row.status) for row in history] == [
        (3, "DRAFT"),
        (2, "PUBLISHED"),
        (1, "ARCHIVED"),
    ]
    archived = await service.get_configuration("MOTOR-001", 1)
    assert archived.configuration["modbus_tcp"]["port"] == 5020


async def test_clone_from_published_creates_the_next_draft(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    v1 = await service.create_draft("MOTOR-001", modbus_payload(port=5020), "tester")
    await service.publish("MOTOR-001", v1.version, "tester")

    clone = await service.clone_version("MOTOR-001", 1, "tester")
    assert clone.version == 2
    assert clone.status == ConfigurationStatus.DRAFT.value
    assert clone.configuration["modbus_tcp"]["port"] == 5020


async def test_rollback_publishes_a_new_version_instead_of_rewriting_history(
    session: AsyncSession,
) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    v1 = await service.create_draft("MOTOR-001", modbus_payload(port=5020), "tester")
    await service.publish("MOTOR-001", v1.version, "tester")
    v2 = await service.create_draft("MOTOR-001", modbus_payload(port=5021), "tester")
    await service.publish("MOTOR-001", v2.version, "tester")

    rollback = await service.clone_version("MOTOR-001", 1, "tester")
    assert rollback.version == 3
    assert rollback.configuration["modbus_tcp"]["port"] == 5020
    row, status = await service.publish("MOTOR-001", rollback.version, "tester")

    assert row.version == 3
    assert row.status == ConfigurationStatus.PUBLISHED.value
    assert status["applied_version"] == 3
    # The original order is untouched: v1 stays archived, v2 is now archived too, v3 is live.
    history = await service.list_configurations("MOTOR-001")
    assert [(item.version, item.status) for item in history] == [
        (3, "PUBLISHED"),
        (2, "ARCHIVED"),
        (1, "ARCHIVED"),
    ]
    versions = [item.version for item in history]
    assert versions == sorted(versions, reverse=True)


async def test_rollback_draft_is_audited(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    v1 = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    await service.publish("MOTOR-001", v1.version, "tester")
    v2 = await service.create_draft("MOTOR-001", modbus_payload(port=5021), "tester")
    await service.publish("MOTOR-001", v2.version, "tester")
    await service.clone_version("MOTOR-001", 1, "tester")

    events = await service.audit_history("MOTOR-001", 50)
    assert ROLLBACK_DRAFT_CREATED in {event["event_type"] for event in events}


async def test_repository_refuses_an_unknown_configuration(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    with pytest.raises(ConfigurationNotFoundError):
        await service.get_configuration("MOTOR-001", 7)


async def test_delete_removes_a_draft_only(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    draft = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    await service.delete_draft("MOTOR-001", draft.version)
    assert await service.list_configurations("MOTOR-001") == []


async def test_audit_history_records_every_lifecycle_event(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    draft = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    await service.validate_version("MOTOR-001", draft.version)
    await service.update_draft("MOTOR-001", draft.version, modbus_payload(port=5023), "tester")
    v2 = await service.create_draft("MOTOR-001", modbus_payload(port=5024), "tester")
    await service.publish("MOTOR-001", v2.version, "tester")
    extra = await service.create_draft("MOTOR-001", modbus_payload(port=5025), "tester")
    await service.delete_draft("MOTOR-001", extra.version)

    events = await service.audit_history("MOTOR-001", 50)
    event_types = [event["event_type"] for event in events]
    for expected in (
        DRAFT_CREATED,
        DRAFT_UPDATED,
        VALIDATED,
        PUBLISHED,
        APPLY_SUCCEEDED,
        DRAFT_DELETED,
    ):
        assert expected in event_types
    assert all(event["device_id"] == "MOTOR-001" for event in events)
    assert any(event["config_version"] == 2 for event in events)


async def test_audit_history_is_scoped_to_one_device(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    await create_device(session, "MOTOR-002")
    service = await _service(session)
    await service.create_draft("MOTOR-001", modbus_payload("MOTOR-001"), "tester")
    await service.create_draft("MOTOR-002", modbus_payload("MOTOR-002"), "tester")

    events = await service.audit_history("MOTOR-002", 50)
    assert events
    assert {event["device_id"] for event in events} == {"MOTOR-002"}


async def test_no_secret_material_reaches_the_audit_trail(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    draft = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    await service.publish("MOTOR-001", draft.version, "tester")

    events = await service.audit_history("MOTOR-001", 50)
    rendered = repr(events)
    for needle in ("password", "token", "secret", "private_key"):
        assert needle not in rendered.lower()


async def test_publish_twice_is_refused(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    draft = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    await service.publish("MOTOR-001", draft.version, "tester")
    with pytest.raises(ConfigurationStateError):
        await service.publish("MOTOR-001", draft.version, "tester")


async def test_archived_version_cannot_be_republished(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    v1 = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    await service.publish("MOTOR-001", v1.version, "tester")
    v2 = await service.create_draft("MOTOR-001", modbus_payload(port=5021), "tester")
    await service.publish("MOTOR-001", v2.version, "tester")

    with pytest.raises(ConfigurationStateError):
        await service.publish("MOTOR-001", 1, "tester")


async def test_validation_is_side_effect_free_on_a_published_version(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    draft = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    await service.publish("MOTOR-001", draft.version, "tester")
    before = await service.get_configuration("MOTOR-001", 1)
    snapshot = dict(before.configuration)
    published_at = before.published_at

    result = await service.validate_version("MOTOR-001", 1)
    assert result["valid"] is True

    after = await service.get_configuration("MOTOR-001", 1)
    assert after.status == ConfigurationStatus.PUBLISHED.value
    assert after.published_at == published_at
    assert dict(after.configuration) == snapshot


async def test_zero_devices_means_no_status(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    status = await service.status("MOTOR-001")
    assert status["desired_version"] is None
    assert status["applied_version"] is None
    assert status["source"] == "none"
    assert status["in_sync"] is False


async def test_published_configuration_round_trips_into_a_typed_definition(
    session: AsyncSession,
) -> None:
    """Gate 9: a published snapshot can be rebuilt into the gateway's own type."""

    from app.gateway.models import DeviceDefinition

    await create_device(session, "MOTOR-003")
    service = await _service(session)
    payload = opcua_payload("MOTOR-003")
    draft = await service.create_draft("MOTOR-003", payload, "tester")
    row, _ = await service.publish("MOTOR-003", draft.version, "tester")

    definition = DeviceDefinition.model_validate(row.configuration)
    assert definition.device_id == "MOTOR-003"
    assert definition.protocol.value == "opc_ua"
    assert definition.opc_ua is not None
    assert set(definition.opc_ua.nodes) == {
        "temperature",
        "bearing_temperature",
        "vibration",
        "current",
        "voltage",
        "rpm",
        "load",
        "power",
    }
    assert definition.opc_ua.endpoint == "opc.tcp://localhost:4840/x"


async def test_events_are_namespaced_per_device_in_the_audit_log(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    resource = await session.scalar(
        text("SELECT resource FROM audit_events ORDER BY timestamp DESC LIMIT 1")
    )
    assert resource == "device_configuration:MOTOR-001"


async def test_archived_event_is_recorded_when_superseded(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    service = await _service(session)
    v1 = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    await service.publish("MOTOR-001", v1.version, "tester")
    v2 = await service.create_draft("MOTOR-001", modbus_payload(port=5021), "tester")
    await service.publish("MOTOR-001", v2.version, "tester")

    events = await service.audit_history("MOTOR-001", 50)
    assert ARCHIVED in {event["event_type"] for event in events}


async def test_apply_failure_is_recorded_as_drift(session: AsyncSession) -> None:
    """Gate 13 and 14: desired and applied diverge, and the failure is not hidden."""

    await create_device(session, "MOTOR-001")
    applier = FakeApplier()
    service = await _service(session, applier)

    v1 = await service.create_draft("MOTOR-001", modbus_payload(port=5020), "tester")
    await service.publish("MOTOR-001", v1.version, "tester")
    assert (await service.status("MOTOR-001"))["applied_version"] == 1

    applier.fail_from_now_on(error="connection refused: localhost:5021")
    v2 = await service.create_draft("MOTOR-001", modbus_payload(port=5021), "tester")
    row, status = await service.publish("MOTOR-001", v2.version, "tester")

    assert row.status == ConfigurationStatus.PUBLISHED.value
    assert status["desired_version"] == 2
    assert status["applied_version"] == 1
    assert status["apply_status"] == "FAILED"
    assert status["in_sync"] is False
    assert status["last_apply_error"] == "connection refused: localhost:5021"

    events = await service.audit_history("MOTOR-001", 50)
    assert APPLY_FAILED in {event["event_type"] for event in events}


async def test_recovery_publishes_a_third_version_and_reconverges(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-001")
    applier = FakeApplier()
    service = await _service(session, applier)

    v1 = await service.create_draft("MOTOR-001", modbus_payload(port=5020), "tester")
    await service.publish("MOTOR-001", v1.version, "tester")
    applier.fail_from_now_on()
    v2 = await service.create_draft("MOTOR-001", modbus_payload(port=5021), "tester")
    await service.publish("MOTOR-001", v2.version, "tester")
    assert (await service.status("MOTOR-001"))["apply_status"] == "FAILED"

    applier.succeed_from_now_on()
    v3 = await service.create_draft("MOTOR-001", modbus_payload(port=5022), "tester")
    await service.publish("MOTOR-001", v3.version, "tester")

    status = await service.status("MOTOR-001")
    assert status["desired_version"] == 3
    assert status["applied_version"] == 3
    assert status["apply_status"] == "APPLIED"
    assert status["in_sync"] is True
    assert status["last_apply_error"] is None


async def test_applying_state_is_visible_while_the_runtime_is_reconfigured(
    session: AsyncSession, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The attempt is committed before the runtime is touched.

    A reader looking at the device while the apply is in flight must see APPLYING
    and the still-absent applied version, rather than either a stale APPLIED claim
    or a hole where the attempt should be.
    """

    await create_device(session, "MOTOR-001")
    applier = BlockingApplier()
    service = await _service(session, applier)
    v1 = await service.create_draft("MOTOR-001", modbus_payload(), "tester")

    publisher = asyncio.create_task(service.publish("MOTOR-001", v1.version, "tester"))
    await asyncio.wait_for(applier.entered.wait(), timeout=10)

    async with sessions() as observer:
        observed = await ConfigurationService(observer, applier).status("MOTOR-001")
    assert observed["apply_status"] == "APPLYING"
    assert observed["desired_version"] == 1
    assert observed["applied_version"] is None
    assert observed["in_sync"] is False

    applier.release.set()
    await asyncio.wait_for(publisher, timeout=10)
    final = await service.status("MOTOR-001")
    assert final["apply_status"] == "APPLIED"
    assert final["applied_version"] == 1
    assert final["in_sync"] is True


async def test_a_raising_applier_is_reported_as_drift_not_an_internal_error(
    session: AsyncSession,
) -> None:
    """A runtime that blows up is a failed apply, not a 500.

    The published version stays published, the previously running runtime is not
    torn down, and the exception text becomes the recorded drift cause.
    """

    await create_device(session, "MOTOR-001")
    applier = FakeApplier()
    service = await _service(session, applier)
    v1 = await service.create_draft("MOTOR-001", modbus_payload(port=5020), "tester")
    await service.publish("MOTOR-001", v1.version, "tester")
    assert (await service.status("MOTOR-001"))["applied_version"] == 1

    applier.raise_from_now_on(RuntimeError("adapter exploded"))
    v2 = await service.create_draft("MOTOR-001", modbus_payload(port=5021), "tester")
    row, status = await service.publish("MOTOR-001", v2.version, "tester")

    assert row.status == ConfigurationStatus.PUBLISHED.value
    assert status["desired_version"] == 2
    assert status["applied_version"] == 1
    assert status["apply_status"] == "FAILED"
    assert status["in_sync"] is False
    assert status["last_apply_error"] == "RuntimeError: adapter exploded"
    assert applier.applied["MOTOR-001"] == 1

    events = await service.audit_history("MOTOR-001", 50)
    assert APPLY_FAILED in {event["event_type"] for event in events}

    applier.succeed_from_now_on()
    recovered = await service.apply_current("MOTOR-001", "tester")
    assert recovered["apply_status"] == "APPLIED"
    assert recovered["applied_version"] == 2
    assert recovered["in_sync"] is True


async def test_publish_without_a_runtime_owner_reports_pending(session: AsyncSession) -> None:
    """No runtime owner in this process means PENDING, never a fabricated APPLIED."""

    await create_device(session, "MOTOR-001")
    service = ConfigurationService(session, FakeApplier(available=False))
    v1 = await service.create_draft("MOTOR-001", modbus_payload(), "tester")
    row, status = await service.publish("MOTOR-001", v1.version, "tester")

    assert row.status == ConfigurationStatus.PUBLISHED.value
    assert status["desired_version"] == 1
    assert status["applied_version"] is None
    assert status["apply_status"] == "PENDING"
    assert status["in_sync"] is False
    assert "not available" in (status["last_apply_error"] or "")

    with pytest.raises(ApplyUnavailableError):
        await service.apply_current("MOTOR-001", "tester")
