"""Registration, login, and the current-identity endpoint, over HTTP.

The requests go through the real application with only the database session
redirected, so the assertions cover the wiring a client actually sees: status
codes, the error envelope, and what the token is allowed to do.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.security.models import User, UserStatus
from app.security.passwords import hash_password
from app.security.tokens import create_access_token
from tests.security.conftest import TEST_JWT_SECRET, TEST_PASSWORD

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


async def register(
    client: AsyncClient, username: str, password: str = TEST_PASSWORD, **extra: object
) -> dict[str, object]:
    response = await client.post(
        REGISTER, json={"username": username, "password": password, **extra}
    )
    return {"status": response.status_code, "body": response.json()}


async def login(
    client: AsyncClient, username: str, password: str = TEST_PASSWORD
) -> dict[str, object]:
    response = await client.post(LOGIN, json={"username": username, "password": password})
    return {"status": response.status_code, "body": response.json()}


async def token_for(client: AsyncClient, username: str, password: str = TEST_PASSWORD) -> str:
    result = await login(client, username, password)
    assert result["status"] == 200, result
    return str(result["body"]["access_token"])  # type: ignore[index]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


async def test_registration_creates_a_read_only_identity(client: AsyncClient) -> None:
    result = await register(client, "self.registered")

    assert result["status"] == 201
    body = result["body"]
    assert body["username"] == "self.registered"  # type: ignore[index]
    assert body["status"] == "ACTIVE"  # type: ignore[index]
    assert body["roles"] == ["VIEWER"]  # type: ignore[index]


async def test_registration_never_echoes_the_password(client: AsyncClient) -> None:
    response = await client.post(
        REGISTER, json={"username": "quiet.user", "password": TEST_PASSWORD}
    )

    assert response.status_code == 201
    assert TEST_PASSWORD not in response.text
    assert "password" not in response.text


async def test_the_username_is_normalised(client: AsyncClient) -> None:
    await register(client, "Mixed.Case")

    result = await login(client, "mixed.case")

    assert result["status"] == 200


async def test_a_duplicate_username_is_refused(client: AsyncClient) -> None:
    await register(client, "duplicate.user")

    result = await register(client, "Duplicate.User")

    assert result["status"] == 409
    assert result["body"]["error"]["code"] == "USERNAME_TAKEN"  # type: ignore[index]


async def test_a_weak_password_is_refused(client: AsyncClient) -> None:
    result = await register(client, "weak.user", password="short")

    assert result["status"] == 422
    assert result["body"]["error"]["code"] == "INVALID_PASSWORD_POLICY"  # type: ignore[index]


async def test_a_self_registering_user_cannot_award_itself_a_role(client: AsyncClient) -> None:
    """``roles`` in the payload is a privilege escalation vector unless gated."""

    result = await register(client, "climber", roles=["ADMIN"])

    assert result["status"] == 201
    assert result["body"]["roles"] == ["VIEWER"]  # type: ignore[index]


async def test_an_administrator_can_grant_a_role_at_registration(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with sessions() as session:
        await _create_user(session, "the.admin", roles=("ADMIN",))
        await session.commit()
    admin_token = await token_for(client, "the.admin")

    response = await client.post(
        REGISTER,
        json={"username": "provisioned.operator", "password": TEST_PASSWORD, "roles": ["OPERATOR"]},
        headers=auth(admin_token),
    )

    assert response.status_code == 201
    assert response.json()["roles"] == ["OPERATOR"]


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #


async def test_login_returns_a_token_and_the_identity(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with sessions() as session:
        user = await _create_user(session, "operator.one", roles=("OPERATOR",))
        await session.commit()

    result = await login(client, "operator.one")

    assert result["status"] == 200
    body = result["body"]
    assert body["token_type"] == "bearer"  # type: ignore[index]
    assert body["user_id"] == str(user.id)  # type: ignore[index]
    assert body["username"] == "operator.one"  # type: ignore[index]
    assert body["roles"] == ["OPERATOR"]  # type: ignore[index]
    assert body["expires_in"] > 0  # type: ignore[index]
    assert body["access_token"]  # type: ignore[index]


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("operator.one", "Wrong-Password-Value-1"),
        ("no.such.user", TEST_PASSWORD),
    ],
)
async def test_a_failed_login_is_indistinguishable(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    username: str,
    password: str,
) -> None:
    """A wrong password and an unknown user must return the same answer."""

    async with sessions() as session:
        await _create_user(session, "operator.one", roles=("OPERATOR",))
        await session.commit()

    result = await login(client, username, password)

    assert result["status"] == 401
    assert result["body"]["error"]["code"] == "INVALID_CREDENTIALS"  # type: ignore[index]


async def test_a_disabled_identity_cannot_authenticate(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with sessions() as session:
        user = await _create_user(session, "retired.operator", roles=("OPERATOR",))
        user.status = UserStatus.DISABLED.value
        await session.commit()

    result = await login(client, "retired.operator")

    assert result["status"] == 401
    assert result["body"]["error"]["code"] == "INVALID_CREDENTIALS"  # type: ignore[index]


# --------------------------------------------------------------------------- #
# Current identity
# --------------------------------------------------------------------------- #


async def test_the_current_identity_requires_a_credential(client: AsyncClient) -> None:
    response = await client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.parametrize("header", ["Bearer not-a-jwt", "Bearer a.b.c", "Basic abc"])
async def test_an_unusable_credential_is_refused(client: AsyncClient, header: str) -> None:
    response = await client.get(ME, headers={"Authorization": header})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_an_expired_token_is_refused_by_code(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with sessions() as session:
        user = await _create_user(session, "operator.one", roles=("OPERATOR",))
        await session.commit()
    expired = create_access_token(
        user_id=user.id,
        username=user.username,
        roles=("OPERATOR",),
        secret=TEST_JWT_SECRET,
        ttl_seconds=60,
        now=datetime.now(UTC) - timedelta(hours=1),
    )

    response = await client.get(ME, headers=auth(expired.token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_the_current_identity_reports_roles_and_permissions(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with sessions() as session:
        user = await _create_user(session, "operator.one", roles=("OPERATOR",))
        await session.commit()
    token = await token_for(client, "operator.one")

    response = await client.get(ME, headers=auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(user.id)
    assert body["status"] == "ACTIVE"
    assert body["roles"] == ["OPERATOR"]
    assert "incident.resolve" in body["permissions"]
    assert "*" not in body["permissions"]
    assert "password_hash" not in response.text


async def test_a_token_for_a_disabled_identity_is_refused(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with sessions() as session:
        user = await _create_user(session, "operator.one", roles=("OPERATOR",))
        await session.commit()
    token = await token_for(client, "operator.one")

    async with sessions() as session:
        row = await session.get(User, user.id)
        assert row is not None
        row.status = UserStatus.DISABLED.value
        await session.commit()

    response = await client.get(ME, headers=auth(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ACCOUNT_DISABLED"


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #


async def test_the_password_is_stored_as_a_hash(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await register(client, "stored.user")

    async with sessions() as session:
        row = await session.scalar(select(User).where(User.username == "stored.user"))

    assert row is not None
    assert TEST_PASSWORD not in row.password_hash
    assert row.password_hash.startswith("$2b$")


async def test_the_database_rejects_an_unknown_status(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The status vocabulary is a check constraint, not a convention."""

    from sqlalchemy.exc import IntegrityError

    async with sessions() as session:
        session.add(
            User(username="bad.status", password_hash=hash_password(TEST_PASSWORD), status="ROOT")
        )
        with pytest.raises(IntegrityError):
            await session.flush()


async def _create_user(session: AsyncSession, username: str, roles: tuple[str, ...]) -> User:
    """Insert an identity with roles, bypassing the registration API."""

    from app.security.repository import RoleRepository, UserRepository

    user = await UserRepository(session).create(
        username=username, password_hash=hash_password(TEST_PASSWORD)
    )
    repository = RoleRepository(session)
    for role in roles:
        await repository.assign(user.id, role)
    await session.flush()
    return user
