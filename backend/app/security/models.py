"""Identity and authorization persistence models.

Five tables, and the normalisation is the design:

``users``            one row per identity. Only a bcrypt hash is stored; the
                     column is named ``password_hash`` so a reader cannot
                     mistake it for something reversible.
``roles``            the named authority bundles.
``permissions``      the ``resource.action`` vocabulary as rows.
``user_roles``       which identity holds which role.
``role_permissions`` which role grants which permission.

Both link tables are plain many-to-many joins with a composite primary key, so
the database itself rejects a duplicate grant instead of relying on the service
to check first.

This module deliberately does not import :mod:`app.models`. ``app.models``
imports *this* module so that Alembic autogenerate can see the tables, and a
back-import would create a cycle at package-import time.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, utc_now


class UserStatus(StrEnum):
    """Lifecycle states of an identity.

    A disabled account keeps its rows and its audit history. It simply cannot
    authenticate, which is the reversible form of removal and the only form an
    audit trail can tolerate.
    """

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


def _status_values() -> str:
    return ", ".join(f"'{status.value}'" for status in UserStatus)


class SecurityTimestampMixin:
    """Creation and modification stamps for the security tables."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class User(SecurityTimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint(f"status IN ({_status_values()})", name="ck_users_status"),
        Index("ix_users_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=UserStatus.ACTIVE.value)


class Role(SecurityTimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("name", name="uq_roles_name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")


class Permission(SecurityTimestampMixin, Base):
    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("name", name="uq_permissions_name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (Index("ix_user_roles_user_id", "user_id"),)

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_user_roles_user_id"),
        primary_key=True,
    )
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE", name="fk_user_roles_role_id"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (Index("ix_role_permissions_role_id", "role_id"),)

    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE", name="fk_role_permissions_role_id"),
        primary_key=True,
    )
    permission_id: Mapped[UUID] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE", name="fk_role_permissions_permission_id"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
