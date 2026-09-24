"""Authentication and identity services.

The service layer holds the two operations that must not be improvised at the
route: registering an identity (which normalises the username, enforces the
password policy, and assigns a role) and authenticating one (which must not
reveal whether a username exists).

Role assignment at registration is deliberately narrow. A caller without the
``user.manage`` permission gets :data:`app.security.rbac.DEFAULT_REGISTRATION_ROLE`
regardless of what the payload asks for, so self-registration can never mint an
administrator.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.security.errors import InvalidCredentialsError, UsernameTakenError
from app.security.models import User, UserStatus
from app.security.passwords import (
    hash_password,
    validate_password_policy,
    verify_dummy_password,
    verify_password,
)
from app.security.rbac import DEFAULT_REGISTRATION_ROLE, Principal
from app.security.repository import RoleRepository, UserRepository, normalize_username


class IdentityService:
    """Build a :class:`Principal` for an already-loaded user row."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.roles = RoleRepository(session)

    async def principal_for(self, user: User) -> Principal:
        roles = await self.roles.names_for_user(user.id)
        permissions = await self.roles.permissions_for_user(user.id)
        return Principal(
            user_id=user.id,
            username=user.username,
            roles=roles,
            permissions=permissions,
        )

    async def roles_for(self, user_id: UUID) -> tuple[str, ...]:
        return await self.roles.names_for_user(user_id)


class AuthService:
    """Registration and credential verification."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.roles = RoleRepository(session)

    async def register(
        self,
        *,
        username: str,
        password: str,
        email: str | None = None,
        roles: tuple[str, ...] | None = None,
    ) -> User:
        """Create an identity and grant it roles.

        ``roles`` is honoured only when the caller passes it; the route decides
        whether the caller is allowed to specify it. Passing ``None`` yields the
        default read-only role.
        """

        normalized = normalize_username(username)
        if await self.users.get_by_username(normalized) is not None:
            raise UsernameTakenError(normalized)
        validate_password_policy(password, username=normalized)
        user = await self.users.create(
            username=normalized,
            password_hash=hash_password(password),
            email=email,
        )
        granted = roles if roles is not None else (DEFAULT_REGISTRATION_ROLE,)
        for role in granted:
            await self.roles.assign(user.id, role)
        await self.session.flush()
        return user

    async def authenticate(self, *, username: str, password: str) -> User:
        """Return the identity behind ``username``/``password`` or raise.

        A missing user still pays the full bcrypt cost before failing, so the
        response time does not disclose which usernames are registered. A
        disabled account is rejected only after the password verifies, for the
        same reason.
        """

        user = await self.users.get_by_username(username)
        if user is None:
            verify_dummy_password(password)
            raise InvalidCredentialsError()
        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()
        if user.status != UserStatus.ACTIVE:
            raise InvalidCredentialsError()
        return user
