"""Authorization enforcement on the incident, workflow, and approval surface.

Every case is an HTTP request through the real application, because the claim
being tested is about the boundary rather than about a helper: a caller with no
identity gets 401, a caller with an identity but no permission gets 403, and a
caller with the permission reaches the route body.

The two errors are asserted by code as well as by status. A 403 that reports
itself as ``AUTHENTICATION_REQUIRED`` would satisfy a status-code assertion and
still be wrong.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Permission, Role, RolePermission, User
from app.security.models import UserStatus
from app.security.passwords import hash_password
from app.security.repository import RoleRepository, UserRepository
from tests.security.conftest import TEST_PASSWORD

INCIDENTS = "/api/v1/incidents"
DASHBOARD = "/api/v1/incidents/dashboard"
WORKFLOWS = "/api/v1/workflows"
WORK_ORDERS = "/api/v1/work-orders"
PENDING_APPROVALS = "/api/v1/approvals/pending"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make_user(sessions: async_sessionmaker[AsyncSession], username: str, role: str) -> None:
    async with sessions() as session:
        user = await UserRepository(session).create(
            username=username, password_hash=hash_password(TEST_PASSWORD)
        )
        await RoleRepository(session).assign(user.id, role)
        await session.commit()


async def token_for(client: AsyncClient, username: str) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


# --------------------------------------------------------------------------- #
# The 401 / 403 boundary
# --------------------------------------------------------------------------- #


async def test_a_request_without_a_credential_is_401(client: AsyncClient) -> None:
    response = await client.get(INCIDENTS)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


async def test_a_request_with_an_identity_but_no_permission_is_403(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "viewer.one", "VIEWER")
    token = await token_for(client, "viewer.one")

    response = await client.post(f"{INCIDENTS}/{uuid4()}/resolve", headers=auth(token))

    assert response.status_code == 403
    body = response.json()["error"]
    assert body["code"] == "PERMISSION_DENIED"
    assert body["details"]["required_permission"] == "incident.resolve"
    assert body["trace_id"]


async def test_the_denial_names_the_permission_that_was_missing(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "viewer.one", "VIEWER")
    token = await token_for(client, "viewer.one")

    response = await client.post(f"{INCIDENTS}/{uuid4()}/start-workflow", headers=auth(token))

    assert response.json()["error"]["details"]["required_permission"] == "workflow.start"


# --------------------------------------------------------------------------- #
# ADMIN
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", [INCIDENTS, DASHBOARD, WORKFLOWS, WORK_ORDERS])
async def test_an_administrator_may_read(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], path: str
) -> None:
    await make_user(sessions, "admin.one", "ADMIN")
    token = await token_for(client, "admin.one")

    response = await client.get(path, headers=auth(token))

    assert response.status_code == 200


async def test_an_administrator_passes_every_permission_check(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The wildcard reaches the route body, which then reports 404 or 503."""

    await make_user(sessions, "admin.one", "ADMIN")
    token = await token_for(client, "admin.one")

    response = await client.post(f"{INCIDENTS}/{uuid4()}/resolve", headers=auth(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INCIDENT_NOT_FOUND"


# --------------------------------------------------------------------------- #
# OPERATOR
# --------------------------------------------------------------------------- #


async def test_an_operator_may_read_the_incident_surface(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")

    assert (await client.get(INCIDENTS, headers=auth(token))).status_code == 200
    assert (await client.get(DASHBOARD, headers=auth(token))).status_code == 200


async def test_an_operator_reaches_the_acknowledge_route_body(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")

    response = await client.post(f"{INCIDENTS}/{uuid4()}/acknowledge", headers=auth(token))

    # 404 rather than 403 proves the permission check passed and the lifecycle
    # service ran; the incident simply does not exist.
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INCIDENT_NOT_FOUND"


async def test_an_operator_reaches_the_workflow_start_route_body(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")

    response = await client.post(f"{INCIDENTS}/{uuid4()}/start-workflow", headers=auth(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "INCIDENT_NOT_FOUND"


async def test_an_operator_may_not_review_an_approval(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """``approval.review`` is an operator permission; its absence must be 403."""

    async with sessions() as session:
        user = await UserRepository(session).create(
            username="readonly.operator", password_hash=hash_password(TEST_PASSWORD)
        )
        repository = RoleRepository(session)
        await repository.assign(user.id, "OPERATOR")
        # OPERATOR holds approval.review by default, so it is revoked here to
        # prove the check reads the database rather than the role name.
        await session.execute(
            delete(RolePermission).where(
                RolePermission.role_id
                == (await session.scalar(select(Role.id).where(Role.name == "OPERATOR"))),
                RolePermission.permission_id
                == (
                    await session.scalar(
                        select(Permission.id).where(Permission.name == "approval.review")
                    )
                ),
            )
        )
        await session.commit()
    token = await token_for(client, "readonly.operator")

    response = await client.post(
        f"/api/v1/approvals/{uuid4()}/approve", json={"reason": "looks fine"}, headers=auth(token)
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["required_permission"] == "approval.review"


# --------------------------------------------------------------------------- #
# VIEWER
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("path", [INCIDENTS, DASHBOARD, WORKFLOWS, WORK_ORDERS])
async def test_a_viewer_may_read(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], path: str
) -> None:
    await make_user(sessions, "viewer.one", "VIEWER")
    token = await token_for(client, "viewer.one")

    response = await client.get(path, headers=auth(token))

    assert response.status_code == 200


async def test_a_viewer_reaches_past_the_approval_permission_check(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """503 rather than 403: the permission was granted and the capability was not
    switched on, which is a different fact from being refused."""

    await make_user(sessions, "viewer.one", "VIEWER")
    token = await token_for(client, "viewer.one")

    response = await client.get(PENDING_APPROVALS, headers=auth(token))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "WORKFLOW_NOT_AVAILABLE"


@pytest.mark.parametrize(
    ("path", "permission"),
    [
        ("/api/v1/incidents/{id}/acknowledge", "incident.ack"),
        ("/api/v1/incidents/{id}/investigate", "incident.investigate"),
        ("/api/v1/incidents/{id}/resolve", "incident.resolve"),
        ("/api/v1/incidents/{id}/close", "incident.close"),
        ("/api/v1/incidents/{id}/reopen", "incident.reopen"),
        ("/api/v1/incidents/{id}/start-workflow", "workflow.start"),
        ("/api/v1/incidents/{id}/workflows", "workflow.start"),
    ],
)
async def test_a_viewer_is_refused_every_write(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    path: str,
    permission: str,
) -> None:
    """Reads and writes are separated by permissions, not by the HTTP verb."""

    await make_user(sessions, "viewer.one", "VIEWER")
    token = await token_for(client, "viewer.one")

    response = await client.post(path.format(id=uuid4()), json={}, headers=auth(token))

    assert response.status_code == 403, response.text
    assert response.json()["error"]["details"]["required_permission"] == permission


# --------------------------------------------------------------------------- #
# The database is authoritative, not the token
# --------------------------------------------------------------------------- #


async def test_revoking_a_grant_takes_effect_on_the_next_request(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """A token minted while a permission was held must stop working once it is
    revoked, which is why permissions are not embedded in the token."""

    await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")
    incident_id = uuid4()
    before = await client.post(f"{INCIDENTS}/{incident_id}/resolve", headers=auth(token))
    assert before.status_code == 404

    async with sessions() as session:
        operator_role = await session.scalar(select(Role.id).where(Role.name == "OPERATOR"))
        permission = await session.scalar(
            select(Permission.id).where(Permission.name == "incident.resolve")
        )
        await session.execute(
            delete(RolePermission).where(
                RolePermission.role_id == operator_role,
                RolePermission.permission_id == permission,
            )
        )
        await session.commit()

    after = await client.post(f"{INCIDENTS}/{incident_id}/resolve", headers=auth(token))

    assert after.status_code == 403
    assert after.json()["error"]["details"]["required_permission"] == "incident.resolve"


async def test_disabling_an_identity_invalidates_its_live_token(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")
    assert (await client.get(INCIDENTS, headers=auth(token))).status_code == 200

    async with sessions() as session:
        user = await session.scalar(select(User).where(User.username == "operator.one"))
        assert user is not None
        user.status = UserStatus.DISABLED.value
        await session.commit()

    response = await client.get(INCIDENTS, headers=auth(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ACCOUNT_DISABLED"


async def test_the_unprotected_surface_is_untouched(client: AsyncClient) -> None:
    """Health must stay reachable: a probe that needs a token cannot be used to
    diagnose a broken login."""

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
