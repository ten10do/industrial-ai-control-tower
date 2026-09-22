"""Asset and configuration HTTP surface.

These tests drive the real application routes against real PostgreSQL. The database
is the subject under test, not a stand-in: the single-published invariant, the
version uniqueness constraint, and the status check constraints are exactly what the
API is expected to translate into 404 / 409 / 422 responses.

The application's lifespan is deliberately not executed. Its dependencies are
injected onto ``app.state`` instead, so no broker, model artifact, or live gateway is
needed to exercise the asset and configuration contract.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assetconfig.apply import UnavailableApplier
from app.assetconfig.models import ApplyStatus, AssetType
from app.main import app
from tests.assetconfig.conftest import FakeApplier, create_device, modbus_payload

V1 = "/api/v1"
LEGACY = "/api"


class _DatabaseShim:
    """Minimal stand-in for ``Database`` that yields sessions from the test engine."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._factory() as session:
            yield session


@pytest.fixture
def applier() -> FakeApplier:
    return FakeApplier()


@pytest.fixture
async def client(
    sessions: async_sessionmaker[AsyncSession], applier: FakeApplier
) -> AsyncIterator[httpx.AsyncClient]:
    app.state.database = _DatabaseShim(sessions)
    app.state.configuration_applier = applier
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://control-tower") as client:
        yield client


def _error(response: httpx.Response) -> tuple[str, str]:
    body = response.json()
    return body["error"]["code"], body["error"]["message"]


async def _device(session: AsyncSession, device_id: str, **kwargs: Any) -> None:
    """Seed a device master row and commit it.

    Committing matters here: the route runs on its own connection, so a flushed but
    uncommitted row would be invisible and every request would look like a 404.
    """

    await create_device(session, device_id, **kwargs)
    await session.commit()


async def _site(client: httpx.AsyncClient, name: str = "Plant A") -> dict[str, Any]:
    response = await client.post(
        f"{V1}/assets",
        json={"name": name, "asset_type": "SITE", "description": "main plant"},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


async def _line(client: httpx.AsyncClient, parent_id: str, name: str = "Line 1") -> dict[str, Any]:
    response = await client.post(
        f"{V1}/assets",
        json={"name": name, "asset_type": "LINE", "parent_id": parent_id},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


# ---------------------------------------------------------------------------
# Asset hierarchy
# ---------------------------------------------------------------------------


async def test_asset_hierarchy_is_created_over_http(client: httpx.AsyncClient) -> None:
    site = await _site(client)
    assert site["asset_type"] == AssetType.SITE.value
    assert site["parent_id"] is None
    assert site["device_count"] == 0
    assert site["metadata"] == {}

    line = await _line(client, site["id"])
    assert line["asset_type"] == AssetType.LINE.value
    assert line["parent_id"] == site["id"]

    listed = await client.get(f"{V1}/assets")
    assert listed.status_code == 200
    assert {node["name"] for node in listed.json()} == {"Plant A", "Line 1"}

    detail = await client.get(f"{V1}/assets/{line['id']}")
    assert detail.status_code == 200
    assert detail.json()["parent_id"] == site["id"]


async def test_a_site_cannot_have_a_parent(client: httpx.AsyncClient) -> None:
    site = await _site(client)
    response = await client.post(
        f"{V1}/assets",
        json={"name": "Nested", "asset_type": "SITE", "parent_id": site["id"]},
    )
    assert response.status_code == 422
    assert _error(response)[0] == "ASSET_HIERARCHY_INVALID"


async def test_a_line_requires_a_parent(client: httpx.AsyncClient) -> None:
    response = await client.post(f"{V1}/assets", json={"name": "Orphan line", "asset_type": "LINE"})
    assert response.status_code == 422
    assert _error(response)[0] == "ASSET_HIERARCHY_INVALID"


async def test_a_line_parent_must_be_a_site(client: httpx.AsyncClient) -> None:
    site = await _site(client)
    line = await _line(client, site["id"])
    response = await client.post(
        f"{V1}/assets",
        json={"name": "Nested line", "asset_type": "LINE", "parent_id": line["id"]},
    )
    assert response.status_code == 422
    assert _error(response)[0] == "ASSET_HIERARCHY_INVALID"


async def test_an_unknown_parent_is_not_found(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"{V1}/assets",
        json={
            "name": "Line 9",
            "asset_type": "LINE",
            "parent_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert response.status_code == 404
    assert _error(response)[0] == "ASSET_NOT_FOUND"


async def test_a_malformed_asset_id_is_a_validation_error(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{V1}/assets/not-a-uuid")
    assert response.status_code == 422
    assert _error(response)[0] == "VALIDATION_ERROR"


async def test_an_unknown_asset_is_not_found(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{V1}/assets/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert _error(response)[0] == "ASSET_NOT_FOUND"


async def test_an_unknown_field_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"{V1}/assets",
        json={"name": "Plant", "asset_type": "SITE", "device_id": "MOTOR-001"},
    )
    assert response.status_code == 422
    assert _error(response)[0] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Device attachment
# ---------------------------------------------------------------------------


async def test_devices_are_attached_and_detached(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001", name="Mill motor")
    await _device(session, "MOTOR-002", name="Conveyor motor")
    site = await _site(client)
    line = await _line(client, site["id"])

    attached = await client.put(f"{V1}/assets/{line['id']}/devices/MOTOR-001")
    assert attached.status_code == 204

    tree = await client.get(f"{V1}/assets/tree")
    assert tree.status_code == 200
    body = tree.json()
    assert len(body["sites"]) == 1
    assert body["sites"][0]["children"][0]["id"] == line["id"]
    attached_ids = [device["device_id"] for device in body["sites"][0]["children"][0]["devices"]]
    assert attached_ids == ["MOTOR-001"]
    assert [device["device_id"] for device in body["unassigned_devices"]] == ["MOTOR-002"]

    detail = await client.get(f"{V1}/assets/{line['id']}")
    assert detail.json()["device_count"] == 1

    detaching = await client.delete(f"{V1}/assets/{line['id']}/devices/MOTOR-001")
    assert detaching.status_code == 204
    after = await client.get(f"{V1}/assets/{line['id']}")
    assert after.json()["device_count"] == 0


async def test_attaching_an_unknown_device_is_not_found(client: httpx.AsyncClient) -> None:
    site = await _site(client)
    response = await client.put(f"{V1}/assets/{site['id']}/devices/MOTOR-404")
    assert response.status_code == 404
    assert _error(response)[0] == "DEVICE_NOT_FOUND"


async def test_detaching_from_the_wrong_asset_conflicts(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    first = await _site(client)
    second = await _site(client, "Plant B")
    await client.put(f"{V1}/assets/{first['id']}/devices/MOTOR-001")

    response = await client.delete(f"{V1}/assets/{second['id']}/devices/MOTOR-001")
    assert response.status_code == 409
    assert _error(response)[0] == "DEVICE_NOT_ATTACHED"


async def test_deleting_an_asset_in_use_conflicts(client: httpx.AsyncClient) -> None:
    site = await _site(client)
    await _line(client, site["id"])

    response = await client.delete(f"{V1}/assets/{site['id']}")
    assert response.status_code == 409
    assert _error(response)[0] == "ASSET_IN_USE"


async def test_deleting_an_empty_asset_succeeds(client: httpx.AsyncClient) -> None:
    site = await _site(client)
    deleted = await client.delete(f"{V1}/assets/{site['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"{V1}/assets")).json() == []


# ---------------------------------------------------------------------------
# Configuration lifecycle
# ---------------------------------------------------------------------------


async def test_the_draft_lifecycle_over_http(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")

    created = await client.post(
        f"{V1}/devices/MOTOR-001/configurations",
        json=modbus_payload(),
        headers={"X-Actor": "operator.one"},
    )
    assert created.status_code == 201, created.text
    draft = created.json()
    assert (draft["version"], draft["status"], draft["protocol"]) == (1, "DRAFT", "modbus_tcp")
    assert draft["created_by"] == "operator.one"
    assert draft["published_at"] is None
    assert draft["configuration"]["modbus_tcp"]["port"] == 5020

    patched = await client.patch(
        f"{V1}/devices/MOTOR-001/configurations/1",
        json=modbus_payload(port=5029),
        headers={"X-Actor": "operator.two"},
    )
    assert patched.status_code == 200
    assert patched.json()["configuration"]["modbus_tcp"]["port"] == 5029

    validated = await client.post(f"{V1}/devices/MOTOR-001/configurations/1/validate")
    assert validated.status_code == 200
    assert validated.json()["valid"] is True
    assert validated.json()["errors"] == []

    refreshed = await client.get(f"{V1}/devices/MOTOR-001/configurations/1")
    assert refreshed.json()["status"] == "VALIDATED"

    history = await client.get(f"{V1}/devices/MOTOR-001/configurations")
    assert history.status_code == 200
    assert [row["version"] for row in history.json()] == [1]

    # Only a DRAFT can be deleted. A validated version is retained as evidence.
    refused = await client.delete(f"{V1}/devices/MOTOR-001/configurations/1")
    assert refused.status_code == 409
    assert _error(refused)[0] == "CONFIGURATION_STATE_INVALID"

    second = await client.post(
        f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload(port=5030)
    )
    assert second.status_code == 201
    assert second.json()["status"] == "DRAFT"
    deleted = await client.delete(f"{V1}/devices/MOTOR-001/configurations/2")
    assert deleted.status_code == 204
    assert [
        row["version"]
        for row in (await client.get(f"{V1}/devices/MOTOR-001/configurations")).json()
    ] == [1]


async def test_an_invalid_payload_is_rejected_at_creation(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    broken = modbus_payload()
    broken["modbus_tcp"]["registers"].pop("power")

    response = await client.post(f"{V1}/devices/MOTOR-001/configurations", json=broken)
    assert response.status_code == 422
    code, _ = _error(response)
    assert code == "CONFIGURATION_VALIDATION_FAILED"
    assert (await client.get(f"{V1}/devices/MOTOR-001/configurations")).json() == []


async def test_a_partial_signal_map_is_never_stored(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """Gate 4: a payload missing canonical signals cannot reach the database.

    The typed validator refuses it on the way in, and the reported codes are the
    same ones the validation pipeline uses, so one mistake reads the same way
    wherever the operator meets it.
    """

    await _device(session, "MOTOR-001")
    partial = modbus_payload()
    partial["modbus_tcp"]["registers"] = {"temperature": {"address": 40001, "scale": 1.0}}

    response = await client.post(f"{V1}/devices/MOTOR-001/configurations", json=partial)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "CONFIGURATION_VALIDATION_FAILED"
    missing = {issue["code"] for issue in error["details"]["errors"]}
    assert missing == {"MISSING_SIGNAL"}
    assert all({"field", "code", "message"} <= set(issue) for issue in error["details"]["errors"])
    assert (await client.get(f"{V1}/devices/MOTOR-001/configurations")).json() == []


async def test_publishing_reports_the_applied_version(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload())

    published = await client.post(f"{V1}/devices/MOTOR-001/configurations/1/publish")
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["configuration"]["status"] == "PUBLISHED"
    assert body["configuration"]["published_at"] is not None
    assert body["status"]["desired_version"] == 1
    assert body["status"]["applied_version"] == 1
    assert body["status"]["apply_status"] == ApplyStatus.APPLIED.value
    assert body["status"]["in_sync"] is True
    assert body["status"]["source"] == "database"

    status = await client.get(f"{V1}/devices/MOTOR-001/configuration-status")
    assert status.json()["in_sync"] is True


async def test_publishing_an_invalid_version_is_refused_with_details(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    """A draft can be structurally sound and still fail validation.

    Here the payload is complete, but the device is not ACTIVE, so publishing is
    refused with structured details and the version stays a DRAFT.
    """

    await _device(session, "MOTOR-001", status="MAINTENANCE")
    created = await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload())
    assert created.status_code == 201

    response = await client.post(f"{V1}/devices/MOTOR-001/configurations/1/publish")
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "CONFIGURATION_VALIDATION_FAILED"
    assert "DEVICE_NOT_ACTIVE" in {issue["code"] for issue in body["details"]["errors"]}
    assert all({"field", "code", "message"} <= set(issue) for issue in body["details"]["errors"])
    assert (await client.get(f"{V1}/devices/MOTOR-001/configurations/1")).json()[
        "status"
    ] == "DRAFT"


async def test_publishing_a_published_version_conflicts(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload())
    await client.post(f"{V1}/devices/MOTOR-001/configurations/1/publish")

    response = await client.post(f"{V1}/devices/MOTOR-001/configurations/1/publish")
    assert response.status_code == 409
    assert _error(response)[0] == "CONFIGURATION_STATE_INVALID"


async def test_a_published_version_is_immutable(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload())
    await client.post(f"{V1}/devices/MOTOR-001/configurations/1/publish")

    patching = await client.patch(
        f"{V1}/devices/MOTOR-001/configurations/1", json=modbus_payload(port=5029)
    )
    assert patching.status_code == 409
    assert _error(patching)[0] == "CONFIGURATION_IMMUTABLE"

    deleting = await client.delete(f"{V1}/devices/MOTOR-001/configurations/1")
    assert deleting.status_code == 409
    assert _error(deleting)[0] == "CONFIGURATION_STATE_INVALID"


async def test_only_one_version_is_published_at_a_time(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload())
    await client.post(f"{V1}/devices/MOTOR-001/configurations/1/publish")
    await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload(port=5021))
    await client.post(f"{V1}/devices/MOTOR-001/configurations/2/publish")

    history = (await client.get(f"{V1}/devices/MOTOR-001/configurations")).json()
    assert [(row["version"], row["status"]) for row in history] == [
        (2, "PUBLISHED"),
        (1, "ARCHIVED"),
    ]


async def test_clone_creates_a_rollback_draft(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload())
    await client.post(f"{V1}/devices/MOTOR-001/configurations/1/publish")
    await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload(port=5021))
    await client.post(f"{V1}/devices/MOTOR-001/configurations/2/publish")

    cloned = await client.post(
        f"{V1}/devices/MOTOR-001/configurations/1/clone", headers={"X-Actor": "operator.one"}
    )
    assert cloned.status_code == 201
    assert cloned.json()["version"] == 3
    assert cloned.json()["status"] == "DRAFT"
    assert cloned.json()["configuration"]["modbus_tcp"]["port"] == 5020

    published = await client.post(f"{V1}/devices/MOTOR-001/configurations/3/publish")
    assert published.status_code == 200
    body = published.json()
    assert body["configuration"]["version"] == 3
    assert body["status"]["desired_version"] == 3
    assert body["status"]["applied_version"] == 3

    events = (await client.get(f"{V1}/devices/MOTOR-001/configuration-audit")).json()
    types = {event["event_type"] for event in events}
    assert "CONFIG_ROLLBACK_DRAFT_CREATED" in types
    assert {"CONFIG_DRAFT_CREATED", "CONFIG_PUBLISHED", "CONFIG_ARCHIVED"} <= types


async def test_an_unknown_device_has_no_configuration(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(f"{V1}/devices/MOTOR-404/configurations")
    assert response.status_code == 404
    assert _error(response)[0] == "DEVICE_NOT_FOUND"

    status = await client.get(f"{V1}/devices/MOTOR-404/configuration-status")
    assert status.status_code == 404


async def test_an_unknown_version_is_not_found(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    response = await client.get(f"{V1}/devices/MOTOR-001/configurations/7")
    assert response.status_code == 404
    assert _error(response)[0] == "CONFIGURATION_NOT_FOUND"


async def test_a_device_id_mismatch_is_refused(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    response = await client.post(
        f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload(device_id="MOTOR-009")
    )
    assert response.status_code == 422
    assert _error(response)[0] == "CONFIGURATION_VALIDATION_FAILED"


async def test_an_inactive_device_cannot_be_configured(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001", status="MAINTENANCE")
    created = await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload())
    assert created.status_code == 201

    validated = await client.post(f"{V1}/devices/MOTOR-001/configurations/1/validate")
    body = validated.json()
    assert body["valid"] is False
    assert "DEVICE_NOT_ACTIVE" in {issue["code"] for issue in body["errors"]}


async def test_secret_material_is_never_accepted(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    payload = modbus_payload()
    payload["opc_ua"] = {"endpoint": "opc.tcp://localhost:4840/x", "password": "hunter2"}

    response = await client.post(f"{V1}/devices/MOTOR-001/configurations", json=payload)
    assert response.status_code == 422
    assert "hunter2" not in response.text
    code, _ = _error(response)
    assert code == "CONFIGURATION_VALIDATION_FAILED"


async def test_the_actor_header_is_validated_and_recorded(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")

    rejected = await client.post(
        f"{V1}/devices/MOTOR-001/configurations",
        json=modbus_payload(),
        headers={"X-Actor": "bad actor!"},
    )
    assert rejected.status_code == 422
    assert _error(rejected)[0] == "INVALID_ACTOR"
    assert (await client.get(f"{V1}/devices/MOTOR-001/configurations")).json() == []

    created = await client.post(
        f"{V1}/devices/MOTOR-001/configurations",
        json=modbus_payload(),
        headers={"X-Actor": "operator.one"},
    )
    assert created.status_code == 201
    events = (await client.get(f"{V1}/devices/MOTOR-001/configuration-audit")).json()
    created_event = next(e for e in events if e["event_type"] == "CONFIG_DRAFT_CREATED")
    assert created_event["actor"] == "operator.one"
    assert created_event["device_id"] == "MOTOR-001"
    assert created_event["config_version"] == 1


async def test_no_actor_header_defaults_to_system(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload())
    events = (await client.get(f"{V1}/devices/MOTOR-001/configuration-audit")).json()
    assert events[0]["actor"] == "system"


async def test_the_audit_history_is_newest_first_and_limitable(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload())
    await client.post(f"{V1}/devices/MOTOR-001/configurations/1/validate")
    await client.post(f"{V1}/devices/MOTOR-001/configurations/1/publish")

    events = (await client.get(f"{V1}/devices/MOTOR-001/configuration-audit")).json()
    timestamps = [event["timestamp"] for event in events]
    assert timestamps == sorted(timestamps, reverse=True)
    assert {"CONFIG_DRAFT_CREATED", "CONFIG_VALIDATED", "CONFIG_PUBLISHED"} <= {
        event["event_type"] for event in events
    }

    limited = await client.get(f"{V1}/devices/MOTOR-001/configuration-audit?limit=1")
    assert len(limited.json()) == 1

    bad_limit = await client.get(f"{V1}/devices/MOTOR-001/configuration-audit?limit=0")
    assert bad_limit.status_code == 422


# ---------------------------------------------------------------------------
# Apply semantics
# ---------------------------------------------------------------------------


async def test_a_failed_apply_is_reported_and_the_previous_runtime_survives(
    client: httpx.AsyncClient, session: AsyncSession, applier: FakeApplier
) -> None:
    await _device(session, "MOTOR-001")
    await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload())
    await client.post(f"{V1}/devices/MOTOR-001/configurations/1/publish")
    assert (await client.get(f"{V1}/devices/MOTOR-001/configuration-status")).json()[
        "applied_version"
    ] == 1

    applier.fail_from_now_on(error="connection refused: localhost:5021")
    await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload(port=5021))
    published = await client.post(f"{V1}/devices/MOTOR-001/configurations/2/publish")
    assert published.status_code == 200
    status = published.json()["status"]
    assert status["desired_version"] == 2
    assert status["applied_version"] == 1
    assert status["apply_status"] == ApplyStatus.FAILED.value
    assert status["in_sync"] is False
    assert status["last_apply_error"] == "connection refused: localhost:5021"

    events = (await client.get(f"{V1}/devices/MOTOR-001/configuration-audit")).json()
    failed = next(e for e in events if e["event_type"] == "CONFIG_APPLY_FAILED")
    assert failed["status"] == "FAILED"
    assert failed["config_version"] == 2

    applier.succeed_from_now_on()
    retried = await client.post(f"{V1}/devices/MOTOR-001/configuration-status/apply")
    assert retried.status_code == 200
    assert retried.json()["apply_status"] == ApplyStatus.APPLIED.value
    assert retried.json()["applied_version"] == 2
    assert retried.json()["in_sync"] is True


async def test_apply_without_a_runtime_owner_is_unavailable(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    app.state.configuration_applier = UnavailableApplier()

    created = await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload())
    assert created.status_code == 201
    published = await client.post(f"{V1}/devices/MOTOR-001/configurations/1/publish")
    assert published.status_code == 200
    status = published.json()["status"]
    assert status["apply_status"] == ApplyStatus.PENDING.value
    assert status["applied_version"] is None
    assert status["in_sync"] is False

    retried = await client.post(f"{V1}/devices/MOTOR-001/configuration-status/apply")
    assert retried.status_code == 503
    assert _error(retried)[0] == "APPLY_UNAVAILABLE"


async def test_apply_is_refused_when_nothing_is_published(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    response = await client.post(f"{V1}/devices/MOTOR-001/configuration-status/apply")
    assert response.status_code == 404
    assert _error(response)[0] == "CONFIGURATION_NOT_FOUND"


async def test_status_reports_protocol_and_runtime_state(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    await client.post(f"{V1}/devices/MOTOR-001/configurations", json=modbus_payload())
    await client.post(f"{V1}/devices/MOTOR-001/configurations/1/publish")

    status = (await client.get(f"{V1}/devices/MOTOR-001/configuration-status")).json()
    assert status["protocol"] == "modbus_tcp"
    assert status["runtime_state"] == "CONNECTED"
    assert status["last_apply_at"] is not None


# ---------------------------------------------------------------------------
# Surface conventions
# ---------------------------------------------------------------------------


async def test_both_prefixes_serve_the_same_surface(
    client: httpx.AsyncClient, session: AsyncSession
) -> None:
    await _device(session, "MOTOR-001")
    for prefix in (V1, LEGACY):
        site = await client.post(
            f"{prefix}/assets", json={"name": f"Plant {prefix}", "asset_type": "SITE"}
        )
        assert site.status_code == 201
        assert (await client.get(f"{prefix}/assets/tree")).status_code == 200
        assert (await client.get(f"{prefix}/devices/MOTOR-001/configurations")).status_code == 200


async def test_the_openapi_surface_is_published() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/assets" in paths
    assert "/api/v1/assets/tree" in paths
    assert "/api/v1/devices/{device_id}/configurations" in paths
    assert "/api/v1/devices/{device_id}/configurations/{version}/validate" in paths
    assert "/api/v1/devices/{device_id}/configurations/{version}/publish" in paths
    assert "/api/v1/devices/{device_id}/configuration-status" in paths
    assert "/api/v1/devices/{device_id}/configuration-audit" in paths
