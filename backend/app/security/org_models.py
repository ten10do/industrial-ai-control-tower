"""Enterprise organization persistence models (Phase 6.13-B).

Five tables, all additive, none of them a second device or asset system:

``organizations``   the enterprise root. One row per legal entity.
``plants``          an organization's manufacturing sites.
``areas``           a plant's zones; the leaf that devices attach to.
``user_scopes``     which subtree of the hierarchy an identity is bound to.
``device_scopes``   the one association between a device master record and an
                    area. The device master stays in ``devices``; this table
                    only names where it lives.

The hierarchy is enforced by foreign keys with ``CASCADE`` deletes: deleting an
organization removes its plants, their areas, the user bindings that name them,
and the device associations under them. Scope is structure, so removing the
structure removes the reach.

``user_scopes.scope_id`` is intentionally a bare UUID with no foreign key: it
names a row in one of three tables depending on ``scope_level``, and SQL has no
polymorphic foreign key. Writes go through the scope API, which validates the
pair before inserting.

This module imports :mod:`app.security.models` and is imported by
:mod:`app.models`, so Alembic autogenerate and the model-comparison tests see
the tables.
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
from app.security.models import SecurityTimestampMixin


class ScopeLevel(StrEnum):
    """The subtree level a user binding names."""

    ORGANIZATION = "ORGANIZATION"
    PLANT = "PLANT"
    AREA = "AREA"


def _scope_level_values() -> str:
    return ", ".join(f"'{level.value}'" for level in ScopeLevel)


class Organization(SecurityTimestampMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("name", name="uq_organizations_name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")


class Plant(SecurityTimestampMixin, Base):
    __tablename__ = "plants"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_plants_org_name"),
        Index("ix_plants_organization_id", "organization_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE", name="fk_plants_organization_id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")


class Area(SecurityTimestampMixin, Base):
    __tablename__ = "areas"
    __table_args__ = (
        UniqueConstraint("plant_id", "name", name="uq_areas_plant_name"),
        Index("ix_areas_plant_id", "plant_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    plant_id: Mapped[UUID] = mapped_column(
        ForeignKey("plants.id", ondelete="CASCADE", name="fk_areas_plant_id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")


class UserScope(SecurityTimestampMixin, Base):
    """One binding between an identity and a subtree of the hierarchy.

    The composite primary key makes a duplicate binding a database rejection,
    the same property ``user_roles`` and ``role_permissions`` carry.
    """

    __tablename__ = "user_scopes"
    __table_args__ = (
        CheckConstraint(
            f"scope_level IN ({_scope_level_values()})",
            name="ck_user_scopes_level",
        ),
        Index("ix_user_scopes_scope", "scope_level", "scope_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_user_scopes_user_id"),
        primary_key=True,
    )
    scope_level: Mapped[str] = mapped_column(String(20), primary_key=True)
    scope_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DeviceScope(SecurityTimestampMixin, Base):
    """The association between a device master record and an area.

    ``device_id`` is the primary key, so a device lives in at most one area:
    reach is a tree, and a device with two homes would make every scope answer
    ambiguous. ``NULL``-free by design: absence of a row means the device is
    unassigned, which every constrained identity treats as out of scope.
    """

    __tablename__ = "device_scopes"

    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.device_id", ondelete="CASCADE", name="fk_device_scopes_device_id"),
        primary_key=True,
    )
    area_id: Mapped[UUID] = mapped_column(
        ForeignKey("areas.id", ondelete="CASCADE", name="fk_device_scopes_area_id"),
        nullable=False,
    )
