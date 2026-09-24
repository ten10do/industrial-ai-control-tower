"""What the security boundary writes to the audit trail.

Three things must be recorded, per the phase spec: a login, a refused
authorization, and a key operation. The last one is the interesting case,
because the row is written by the pre-existing incident lifecycle service, which
knows nothing about authentication. It carries the identity anyway, and that is
the point of publishing the caller into the request-scoped security context.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AuditEvent, Device, Incident
from app.security.passwords import hash_password
from app.security.repository import RoleRepository, UserRepository
from tests.security.conftest import TEST_PASSWORD

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"

UNIFIED_KEYS = {"actor", "action", "resource", "resource_id", "status"}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make_user(sessions: async_sessionmaker[AsyncSession], username: str, role: str) -> UUID:
    async with sessions() as session:
        user = await UserRepository(session).create(
            username=username, password_hash=hash_password(TEST_PASSWORD)
        )
        await RoleRepository(session).assign(user.id, role)
        await session.commit()
        return user.id


async def token_for(client: AsyncClient, username: str) -> str:
    response = await client.post(LOGIN, json={"username": username, "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


async def events(sessions: async_sessionmaker[AsyncSession], **filters: object) -> list[AuditEvent]:
    async with sessions() as session:
        statement = select(AuditEvent).order_by(AuditEvent.timestamp.asc())
        for column, value in filters.items():
            statement = statement.where(getattr(AuditEvent, column) == value)
        return list(await session.scalars(statement))


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #


async def test_a_successful_login_is_audited_with_the_identity(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await make_user(sessions, "operator.one", "OPERATOR")

    token = await token_for(client, "operator.one")

    assert token
    rows = await events(sessions, action="AUTH_LOGIN", resource="auth")
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "SUCCESS"
    assert row.actor == "operator.one"
    assert row.actor_user_id == user_id
    assert row.resource_id == str(user_id)
    assert row.ip_address
    assert row.details["roles"] == ["OPERATOR"]


async def test_a_failed_login_is_audited_without_an_identity(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "operator.one", "OPERATOR")

    response = await client.post(
        LOGIN, json={"username": "operator.one", "password": "Wrong-Password-Value-1"}
    )

    assert response.status_code == 401
    rows = await events(sessions, action="AUTH_LOGIN")
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "FAILURE"
    assert row.actor == "operator.one"
    assert row.actor_user_id is None
    assert row.resource_id == "operator.one"
    assert row.details["reason"] == "INVALID_CREDENTIALS"


async def test_registration_is_audited(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    response = await client.post(REGISTER, json={"username": "new.user", "password": TEST_PASSWORD})

    assert response.status_code == 201
    rows = await events(sessions, action="AUTH_REGISTER")
    assert len(rows) == 1
    assert rows[0].details["registered_by"] == "self"


# --------------------------------------------------------------------------- #
# Authorization
# --------------------------------------------------------------------------- #


async def test_a_refused_authorization_is_audited(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await make_user(sessions, "viewer.one", "VIEWER")
    token = await token_for(client, "viewer.one")

    response = await client.post(
        "/api/v1/incidents/2f1d0b32-0000-4000-8000-000000000001/resolve",
        headers=auth(token),
    )

    assert response.status_code == 403
    rows = await events(sessions, action="PERMISSION_DENIED")
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "DENIED"
    assert row.actor == "viewer.one"
    assert row.actor_user_id == user_id
    assert row.resource == "permission"
    assert row.resource_id == "incident.resolve"
    assert row.details["path"].startswith("/api/v1/incidents/")
    assert row.details["roles"] == ["VIEWER"]
    assert row.ip_address


async def test_the_refusal_is_audited_before_the_route_body_runs(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The denied request must leave exactly one audit row and change nothing."""

    await make_user(sessions, "viewer.one", "VIEWER")
    token = await token_for(client, "viewer.one")

    await client.post(
        "/api/v1/incidents/2f1d0b32-0000-4000-8000-000000000002/resolve", headers=auth(token)
    )

    assert len(await events(sessions, action="PERMISSION_DENIED")) == 1
    assert await events(sessions, action="INCIDENT_RESOLVED") == []


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #


async def test_an_incident_acknowledgement_carries_the_authenticated_actor(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The lifecycle service is unchanged and still records who acted."""

    user_id = await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")
    incident_id = await seed_incident(sessions)

    response = await client.post(
        f"/api/v1/incidents/{incident_id}/acknowledge", json={}, headers=auth(token)
    )

    assert response.status_code == 200, response.text
    rows = await events(sessions, resource=str(incident_id))
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "INCIDENT_ACKNOWLEDGED"
    assert row.actor == "operator.one"
    assert row.actor_user_id == user_id
    assert row.ip_address
    assert row.user_agent


async def test_the_operation_row_keeps_the_legacy_resource_column(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The incident timeline queries ``resource == <incident id>``; the identity
    columns are additive and must not have moved that value."""

    await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")
    incident_id = await seed_incident(sessions)

    await client.post(f"/api/v1/incidents/{incident_id}/acknowledge", json={}, headers=auth(token))

    rows = await events(sessions, resource=str(incident_id))
    assert rows, "the incident timeline query must still find the row"


async def test_a_security_row_follows_the_unified_format(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The documented shape of a security-boundary row."""

    await make_user(sessions, "viewer.one", "VIEWER")
    token = await token_for(client, "viewer.one")
    await client.post(
        "/api/v1/incidents/2f1d0b32-0000-4000-8000-000000000003/resolve", headers=auth(token)
    )

    row = (await events(sessions, action="PERMISSION_DENIED"))[0]
    rendered = {
        "actor": row.actor,
        "action": row.action,
        "resource": row.resource,
        "resource_id": row.resource_id,
        "status": row.status,
    }

    assert set(rendered) == UNIFIED_KEYS
    assert rendered["resource"] == "permission"
    assert rendered["status"] == "DENIED"


async def test_an_unexpected_error_is_not_recorded_as_a_denial(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Only refusals are audited as refusals."""

    await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")

    response = await client.post(
        "/api/v1/incidents/2f1d0b32-0000-4000-8000-000000000004/resolve", headers=auth(token)
    )

    assert response.status_code == 404
    assert await events(sessions, action="PERMISSION_DENIED") == []


async def seed_incident(sessions: async_sessionmaker[AsyncSession]) -> UUID:
    async with sessions() as session:
        session.add(
            Device(
                device_id="MOTOR-612",
                device_type="MOTOR",
                name="MOTOR-612",
                status="ACTIVE",
                device_metadata={},
            )
        )
        await session.flush()
        incident = Incident(
            device_id="MOTOR-612",
            title="Audit fixture incident",
            description="",
            status="OPEN",
            priority="MEDIUM",
        )
        session.add(incident)
        await session.commit()
        return incident.id


@pytest.mark.parametrize("action", ["AUTH_LOGIN", "PERMISSION_DENIED"])
async def test_security_rows_are_committed_even_when_the_request_fails(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], action: str
) -> None:
    """A refused request still has to leave evidence behind."""

    await make_user(sessions, "viewer.one", "VIEWER")
    await client.post(LOGIN, json={"username": "viewer.one", "password": "Wrong-Password-Value-1"})
    token = await token_for(client, "viewer.one")
    await client.post(
        "/api/v1/incidents/2f1d0b32-0000-4000-8000-000000000005/resolve", headers=auth(token)
    )

    assert await events(sessions, action=action)
