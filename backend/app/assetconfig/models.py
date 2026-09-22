"""Phase 6.8 persistence models for asset hierarchy and device configuration.

Three tables are added, and one column is added to ``devices``:

* ``asset_nodes`` holds the minimal SITE / LINE hierarchy. It is a location tree,
  not a CMDB, and it deliberately stops at the depth the domain model needs.
* ``device_configurations`` holds immutable version snapshots of one device's
  telemetry acquisition configuration.
* ``device_configuration_runtime_status`` holds the observed runtime state that
  must never be mixed into the immutable snapshots.
* ``devices.asset_node_id`` links the existing device master row to the tree.

Device identity is unchanged. ``devices.device_id`` remains the single identity
source and every configuration row references it. No parallel device table is
introduced, because a second identity system would make "which device is this"
ambiguous.

Configuration lifecycle::

    DRAFT -> VALIDATED -> PUBLISHED -> ARCHIVED

Only ``DRAFT`` rows are mutable. A published snapshot is never edited in place,
so history stays reproducible and the runtime can name the exact version it ran.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, utc_now


class AssetType(StrEnum):
    """Levels supported by the minimal asset hierarchy."""

    SITE = "SITE"
    LINE = "LINE"


class ConfigurationStatus(StrEnum):
    """Lifecycle status of one configuration version snapshot."""

    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class ApplyStatus(StrEnum):
    """Outcome of the most recent attempt to apply a published version."""

    PENDING = "PENDING"
    APPLYING = "APPLYING"
    APPLIED = "APPLIED"
    FAILED = "FAILED"


class ConfigurationSource(StrEnum):
    """Where a running device runtime took its definition from."""

    DATABASE = "database"
    BOOTSTRAP = "bootstrap"
    NONE = "none"


ASSET_PARENT_RULES: dict[AssetType, AssetType | None] = {
    AssetType.SITE: None,
    AssetType.LINE: AssetType.SITE,
}


class AssetNode(Base):
    """One node in the minimal location hierarchy.

    ``SITE`` nodes are roots. ``LINE`` nodes must have a ``SITE`` parent. A parent
    cannot be removed while it still has children, and a node cannot be removed
    while a device points at it, so no orphan child can exist.
    """

    __tablename__ = "asset_nodes"
    __table_args__ = (
        CheckConstraint("asset_type IN ('SITE', 'LINE')", name="ck_asset_nodes_type"),
        CheckConstraint(
            "(asset_type = 'SITE' AND parent_id IS NULL) "
            "OR (asset_type = 'LINE' AND parent_id IS NOT NULL)",
            name="ck_asset_nodes_parent_shape",
        ),
        Index("ix_asset_nodes_parent_id", "parent_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("asset_nodes.id", ondelete="RESTRICT", name="fk_asset_nodes_parent_id"),
        nullable=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    node_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class DeviceConfiguration(Base):
    """One immutable version snapshot of a device's acquisition configuration."""

    __tablename__ = "device_configurations"
    __table_args__ = (
        UniqueConstraint("device_id", "version", name="uq_device_configurations_device_version"),
        CheckConstraint("version > 0", name="ck_device_configurations_version_positive"),
        CheckConstraint(
            "status IN ('DRAFT', 'VALIDATED', 'PUBLISHED', 'ARCHIVED')",
            name="ck_device_configurations_status",
        ),
        CheckConstraint(
            "(status IN ('PUBLISHED', 'ARCHIVED')) = (published_at IS NOT NULL)",
            name="ck_device_configurations_published_at",
        ),
        Index("ix_device_configurations_device_status", "device_id", "status"),
        Index(
            "uq_device_configurations_single_published",
            "device_id",
            unique=True,
            postgresql_where=text("status = 'PUBLISHED'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    device_id: Mapped[str] = mapped_column(
        ForeignKey(
            "devices.device_id", ondelete="RESTRICT", name="fk_device_configurations_device"
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    protocol: Mapped[str] = mapped_column(String(20), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False, default="system")
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validation_result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    validation_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class DeviceConfigurationRuntimeStatus(Base):
    """Observed runtime state for one device's configuration.

    This is deliberately a separate table. Desired and applied versions describe
    what is running right now, while ``device_configurations`` rows are immutable
    evidence. Mixing them would make a snapshot mutate after publication.
    """

    __tablename__ = "device_configuration_runtime_status"
    __table_args__ = (
        CheckConstraint(
            "apply_status IN ('PENDING', 'APPLYING', 'APPLIED', 'FAILED')",
            name="ck_device_configuration_runtime_apply_status",
        ),
        CheckConstraint(
            "source IN ('database', 'bootstrap', 'none')",
            name="ck_device_configuration_runtime_source",
        ),
    )

    device_id: Mapped[str] = mapped_column(
        ForeignKey(
            "devices.device_id",
            ondelete="CASCADE",
            name="fk_device_configuration_runtime_status_device",
        ),
        primary_key=True,
    )
    desired_version: Mapped[int | None] = mapped_column(Integer)
    applied_version: Mapped[int | None] = mapped_column(Integer)
    apply_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    last_apply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_apply_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
