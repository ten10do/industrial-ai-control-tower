"""Read and write access to the identity tables.

The repository is where the "roles and permissions live in the database"
promise is kept. Authorization reads go through here and hit real rows, so
revoking a grant takes effect on the next request. Nothing in this module
caches.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.security.errors import UnknownRoleError
from app.security.models import Permission, Role, RolePermission, User, UserRole, UserStatus


def normalize_username(username: str) -> str:
    """Return the canonical form of a username.

    Case is folded and surrounding whitespace is removed, so ``Operator.One``
    and ``operator.one`` are one identity rather than two that look alike.
    Uniqueness is then a plain unique constraint instead of a functional index.
    """

    return username.strip().casefold()


def normalize_email(email: str | None) -> str | None:
    if email is None:
        return None
    cleaned = email.strip().casefold()
    return cleaned or None


class UserRepository:
    """Identity records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_username(self, username: str) -> User | None:
        statement = select(User).where(User.username == normalize_username(username))
        return cast(User | None, await self.session.scalar(statement))

    async def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == normalize_email(email))
        return cast(User | None, await self.session.scalar(statement))

    async def create(
        self,
        *,
        username: str,
        password_hash: str,
        email: str | None = None,
        status: UserStatus = UserStatus.ACTIVE,
    ) -> User:
        user = User(
            username=normalize_username(username),
            email=normalize_email(email),
            password_hash=password_hash,
            status=status.value,
        )
        self.session.add(user)
        await self.session.flush()
        return user


class RoleRepository:
    """Roles, their permissions, and who holds them."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_name(self, name: str) -> Role | None:
        statement = select(Role).where(Role.name == name.upper())
        return cast(Role | None, await self.session.scalar(statement))

    async def role_names(self) -> tuple[str, ...]:
        rows = await self.session.scalars(select(Role.name).order_by(Role.name))
        return tuple(rows)

    async def names_for_user(self, user_id: UUID) -> tuple[str, ...]:
        statement = (
            select(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.name)
        )
        return tuple(await self.session.scalars(statement))

    async def permissions_for_user(self, user_id: UUID) -> frozenset[str]:
        """Return the effective permission set of one identity.

        This is the single authorization query of the platform. It joins the
        identity to its roles and the roles to their permissions; the result is
        what ``require_permission`` checks.
        """

        statement = (
            select(Permission.name)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
        )
        return frozenset(await self.session.scalars(statement))

    async def assign(self, user_id: UUID, role_name: str) -> None:
        """Grant one role. Idempotent: a duplicate grant is a no-op."""

        role = await self.get_by_name(role_name)
        if role is None:
            raise UnknownRoleError(role_name)
        existing = await self.session.scalar(
            select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id)
        )
        if existing is None:
            self.session.add(UserRole(user_id=user_id, role_id=role.id))
            await self.session.flush()


class RoleSeedRepository:
    """Write side of the role/permission seed, used by the migration helper."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def clear_user_roles(self, user_id: UUID) -> None:
        await self.session.execute(delete(UserRole).where(UserRole.user_id == user_id))
