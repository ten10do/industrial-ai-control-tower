"""Phase 6.13-A: the migrated surface answers to identity, not to headers.

Phase 6.12 left a documented gap: alarms, alarm rules, assets, device
configuration, connectivity, and observability still accepted a caller-supplied
``X-Actor`` label as their audit actor. This suite proves the gap is closed.

Four claims, each an HTTP request through the real application:

1. A request without a credential is 401 on every migrated route, read or
   write.
2. An identity without the permission is 403, and the refusal names the
   permission.
3. A forged ``X-Actor`` header cannot become the audit actor: the row records
   the authenticated identity, and the forged label survives only as
   ``details["legacy_x_actor"]`` metadata.
4. A business mutation writes ``actor_user_id`` on ``audit_events``, so "who
   did this" is answerable from the audit trail alone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Alarm, AuditEvent, Device
from app.security.passwords import hash_password
from app.security.repository import RoleRepository, UserRepository
from tests.security.conftest import TEST_PASSWORD

ALARMS = "/api/v1/alarms"
ALARM_RULES = "/api/v1/alarm-rules"
ASSETS = "/api/v1/assets"
CONNECTIVITY = "/api/v1/connectivity/devices/MOTOR-001/start"
CONNECTIVITY_SUMMARY = "/api/v1/connectivity/summary"
OBSERVABILITY = "/api/v1/observability/runs"
CONFIGURATIONS = "/api/v1/devices/MOTOR-404/configurations"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def legacy(label: str) -> dict[str, str]:
    return {"X-Actor": label}


async def make_user(sessions: async_sessionmaker[AsyncSession], username: str, role: str) -> object:
    async with sessions() as session:
        user = await UserRepository(session).create(
            username=username, password_hash=hash_password(TEST_PASSWORD)
        )
        await RoleRepository(session).assign(user.id, role)
        await session.commit()
        return user.id


async def token_for(client: AsyncClient, username: str) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


async def events(sessions: async_sessionmaker[AsyncSession], **filters: object) -> list[AuditEvent]:
    async with sessions() as session:
        statement = select(AuditEvent).order_by(AuditEvent.timestamp.asc())
        for column, value in filters.items():
            statement = statement.where(getattr(AuditEvent, column) == value)
        return list(await session.scalars(statement))


async def seed_alarm(sessions: async_sessionmaker[AsyncSession]) -> object:
    async with sessions() as session:
        session.add(
            Device(
                device_id="MOTOR-613",
                device_type="MOTOR",
                name="MOTOR-613",
                status="ACTIVE",
                device_metadata={},
            )
        )
        await session.flush()
        alarm = Alarm(
            device_id="MOTOR-613",
            rule_id="temperature_high",
            severity="CRITICAL",
            status="ACTIVE",
            message="95 °C > 90 °C",
            started_at=datetime.now(UTC),
            occurrence_count=1,
        )
        session.add(alarm)
        await session.commit()
        return alarm.id


# --------------------------------------------------------------------------- #
# 1. Anonymous requests
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", ALARMS),
        ("GET", ALARM_RULES),
        ("GET", ASSETS),
        ("GET", OBSERVABILITY),
        ("GET", CONNECTIVITY_SUMMARY),
        ("POST", f"{ALARMS}/{uuid4()}/acknowledge"),
        ("POST", f"{ALARMS}/{uuid4()}/clear"),
        ("POST", ALARM_RULES),
        ("POST", ASSETS),
        ("POST", CONNECTIVITY),
        ("POST", f"{CONFIGURATIONS}/1/publish"),
    ],
)
async def test_an_anonymous_request_is_401_on_the_migrated_surface(
    client: AsyncClient, method: str, path: str
) -> None:
    """No identity, no access: reads and writes are refused alike."""

    response = await client.request(method, path, json={})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


async def test_an_anonymous_request_with_a_forged_label_is_still_401(
    client: AsyncClient,
) -> None:
    """A header is not a credential: ``X-Actor`` cannot substitute for one."""

    response = await client.get(ALARMS, headers=legacy("operator.one"))

    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# 2. Insufficient permission
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("method", "path", "permission"),
    [
        ("POST", f"{ALARMS}/{uuid4()}/acknowledge", "alarm.ack"),
        ("POST", f"{ALARMS}/{uuid4()}/clear", "alarm.clear"),
        ("POST", ALARM_RULES, "alarmrule.create"),
        ("PATCH", f"{ALARM_RULES}/temperature_high", "alarmrule.update"),
        ("POST", ASSETS, "asset.manage"),
        ("POST", CONNECTIVITY, "connectivity.control"),
        ("POST", f"{CONFIGURATIONS}/1/publish", "config.publish"),
    ],
)
async def test_a_viewer_is_refused_every_migrated_write(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    method: str,
    path: str,
    permission: str,
) -> None:
    await make_user(sessions, "viewer.one", "VIEWER")
    token = await token_for(client, "viewer.one")

    response = await client.request(method, path, json={}, headers=auth(token))

    assert response.status_code == 403, response.text
    body = response.json()["error"]
    assert body["code"] == "PERMISSION_DENIED"
    assert body["details"]["required_permission"] == permission


async def test_an_operator_may_read_the_migrated_surface(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")

    assert (await client.get(ALARMS, headers=auth(token))).status_code == 200
    assert (await client.get(ALARM_RULES, headers=auth(token))).status_code == 200
    assert (await client.get(ASSETS, headers=auth(token))).status_code == 200


# --------------------------------------------------------------------------- #
# 3. The forged header is metadata, never attribution
# --------------------------------------------------------------------------- #


async def test_a_forged_label_does_not_become_the_audit_actor(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The classic pre-6.13 forgery: claim someone else's name and act.

    The request succeeds — the caller holds ``alarm.ack`` — but the audit row
    records the authenticated identity. The forged label survives only as
    ``legacy_x_actor`` metadata next to it, and the alarm row attributes the
    acknowledgement to the real operator.
    """

    user_id = await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")
    alarm_id = await seed_alarm(sessions)

    response = await client.post(
        f"{ALARMS}/{alarm_id}/acknowledge",
        json={},
        headers={**auth(token), **legacy("attacker")},
    )

    assert response.status_code == 200, response.text
    rows = await events(sessions, action="ALARM_ACKNOWLEDGED")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor == "operator.one"
    assert row.actor_user_id == user_id
    assert row.details["legacy_x_actor"] == "attacker"

    async with sessions() as session:
        alarm = await session.get(Alarm, alarm_id)
        assert alarm is not None
        assert alarm.acknowledged_by == "operator.one"


async def test_an_absent_label_leaves_no_legacy_metadata(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The metadata key appears only when a client actually sent the header."""

    await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")
    alarm_id = await seed_alarm(sessions)

    await client.post(f"{ALARMS}/{alarm_id}/acknowledge", json={}, headers=auth(token))

    rows = await events(sessions, action="ALARM_ACKNOWLEDGED")
    assert rows and "legacy_x_actor" not in rows[0].details


async def test_a_malformed_label_no_longer_fails_an_authenticated_request(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Pre-6.13 this was a 422; a legacy label is metadata and cannot break a
    request the caller is otherwise entitled to make."""

    await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")

    response = await client.get(ALARMS, headers={**auth(token), **legacy("bad actor!")})

    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# 4. Audit attribution carries the user id
# --------------------------------------------------------------------------- #


async def test_an_alarm_acknowledgement_writes_actor_user_id(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The headline claim: ``audit_events`` names the identity, not a label."""

    user_id = await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")
    alarm_id = await seed_alarm(sessions)

    response = await client.post(f"{ALARMS}/{alarm_id}/acknowledge", json={}, headers=auth(token))

    assert response.status_code == 200, response.text
    rows = await events(sessions, action="ALARM_ACKNOWLEDGED")
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "SUCCESS"
    assert row.actor == "operator.one"
    assert row.actor_user_id == user_id
    assert row.ip_address
    assert row.user_agent


async def test_a_rule_creation_writes_actor_user_id(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")

    response = await client.post(
        ALARM_RULES,
        json={
            "id": "pressure_high",
            "name": "pressure high",
            "signal_name": "temperature",
            "operator": "GT",
            "threshold": 90.0,
            "severity": "MAJOR",
        },
        headers=auth(token),
    )

    assert response.status_code == 201, response.text
    rows = await events(sessions, action="ALARM_RULE_CREATED")
    assert len(rows) == 1
    assert rows[0].actor == "operator.one"
    assert rows[0].actor_user_id == user_id
    assert rows[0].resource == "pressure_high"


async def test_a_denied_mutation_is_audited_as_a_denial(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """A refusal on the migrated surface leaves the same evidence as 6.12."""

    user_id = await make_user(sessions, "viewer.one", "VIEWER")
    token = await token_for(client, "viewer.one")

    response = await client.post(f"{ALARMS}/{uuid4()}/acknowledge", json={}, headers=auth(token))

    assert response.status_code == 403
    rows = await events(sessions, action="PERMISSION_DENIED")
    assert len(rows) == 1
    assert rows[0].actor_user_id == user_id
    assert rows[0].resource_id == "alarm.ack"
