"""Persistence access for the asset hierarchy and versioned device configuration.

Device master rows remain in the existing ``devices`` table. This module reads
them for the tree view and writes exactly one new column, ``asset_node_id``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.assetconfig.models import (
    ApplyStatus,
    AssetNode,
    ConfigurationSource,
    ConfigurationStatus,
    DeviceConfiguration,
    DeviceConfigurationRuntimeStatus,
)
from app.models import AuditEvent, Device

CONFIG_AUDIT_RESOURCE_PREFIX = "device_configuration:"


def config_audit_resource(device_id: str) -> str:
    """Return the audit resource key used for one device's configuration events."""

    return f"{CONFIG_AUDIT_RESOURCE_PREFIX}{device_id}"


class AssetRepository:
    """Queries over the minimal asset hierarchy and its device links."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, node: AssetNode) -> AssetNode:
        self.session.add(node)
        await self.session.flush()
        return node

    async def get(self, node_id: UUID) -> AssetNode | None:
        return cast(
            AssetNode | None,
            await self.session.scalar(select(AssetNode).where(AssetNode.id == node_id)),
        )

    async def list_all(self) -> list[AssetNode]:
        rows = await self.session.scalars(
            select(AssetNode).order_by(AssetNode.asset_type.desc(), AssetNode.name)
        )
        return list(rows)

    async def child_count(self, node_id: UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).select_from(AssetNode).where(AssetNode.parent_id == node_id)
            )
            or 0
        )

    async def device_count(self, node_id: UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).select_from(Device).where(Device.asset_node_id == node_id)
            )
            or 0
        )

    async def device_counts(self) -> dict[UUID, int]:
        rows = await self.session.execute(
            select(Device.asset_node_id, func.count())
            .where(Device.asset_node_id.is_not(None))
            .group_by(Device.asset_node_id)
        )
        return {node_id: int(count) for node_id, count in rows if node_id is not None}

    async def delete(self, node: AssetNode) -> None:
        await self.session.delete(node)
        await self.session.flush()


class DeviceQueryRepository:
    """Read and write access to device master rows needed by this phase."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, device_id: str) -> Device | None:
        return cast(
            Device | None,
            await self.session.scalar(select(Device).where(Device.device_id == device_id)),
        )

    async def list_all(self) -> list[Device]:
        rows = await self.session.scalars(select(Device).order_by(Device.device_id))
        return list(rows)

    async def assign_asset(self, device: Device, node_id: UUID | None) -> None:
        device.asset_node_id = node_id
        await self.session.flush()


class ConfigurationRepository:
    """Queries over versioned device configurations and runtime status."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_version(self, device_id: str) -> int:
        highest = await self.session.scalar(
            select(func.max(DeviceConfiguration.version)).where(
                DeviceConfiguration.device_id == device_id
            )
        )
        return int(highest or 0) + 1

    async def create(self, row: DeviceConfiguration) -> DeviceConfiguration:
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, device_id: str, version: int) -> DeviceConfiguration | None:
        return cast(
            DeviceConfiguration | None,
            await self.session.scalar(
                select(DeviceConfiguration).where(
                    DeviceConfiguration.device_id == device_id,
                    DeviceConfiguration.version == version,
                )
            ),
        )

    async def list_for_device(self, device_id: str) -> list[DeviceConfiguration]:
        rows = await self.session.scalars(
            select(DeviceConfiguration)
            .where(DeviceConfiguration.device_id == device_id)
            .order_by(DeviceConfiguration.version.desc())
        )
        return list(rows)

    async def current_published(self, device_id: str) -> DeviceConfiguration | None:
        return cast(
            DeviceConfiguration | None,
            await self.session.scalar(
                select(DeviceConfiguration).where(
                    DeviceConfiguration.device_id == device_id,
                    DeviceConfiguration.status == ConfigurationStatus.PUBLISHED.value,
                )
            ),
        )

    async def list_published(self) -> list[DeviceConfiguration]:
        rows = await self.session.scalars(
            select(DeviceConfiguration)
            .where(DeviceConfiguration.status == ConfigurationStatus.PUBLISHED.value)
            .order_by(DeviceConfiguration.device_id)
        )
        return list(rows)

    async def archive_published_except(self, device_id: str, keep_version: int) -> int:
        result = cast(
            CursorResult[Any],
            await self.session.execute(
                update(DeviceConfiguration)
                .where(
                    DeviceConfiguration.device_id == device_id,
                    DeviceConfiguration.status == ConfigurationStatus.PUBLISHED.value,
                    DeviceConfiguration.version != keep_version,
                )
                .values(
                    status=ConfigurationStatus.ARCHIVED.value,
                    archived_at=func.now(),
                )
                # ``fetch`` synchronisation is deliberate. The demoted row is very
                # likely already resident in the session, and a blind bulk UPDATE would
                # leave it holding a stale ``PUBLISHED`` status in memory while the
                # database says ARCHIVED. Fetching the affected primary keys and
                # expiring their stale attributes keeps the ORM view and the database
                # view consistent.
                .execution_options(synchronize_session="fetch")
            ),
        )
        return int(result.rowcount or 0)

    async def delete(self, row: DeviceConfiguration) -> None:
        await self.session.delete(row)
        await self.session.flush()

    async def runtime_status(self, device_id: str) -> DeviceConfigurationRuntimeStatus | None:
        return cast(
            DeviceConfigurationRuntimeStatus | None,
            await self.session.scalar(
                select(DeviceConfigurationRuntimeStatus).where(
                    DeviceConfigurationRuntimeStatus.device_id == device_id
                )
            ),
        )

    async def list_runtime_status(self) -> list[DeviceConfigurationRuntimeStatus]:
        rows = await self.session.scalars(
            select(DeviceConfigurationRuntimeStatus).order_by(
                DeviceConfigurationRuntimeStatus.device_id
            )
        )
        return list(rows)

    async def upsert_runtime_status(
        self,
        *,
        device_id: str,
        desired_version: int | None,
        applied_version: int | None,
        apply_status: ApplyStatus,
        source: ConfigurationSource,
        last_apply_at: Any,
        last_apply_error: str | None,
    ) -> DeviceConfigurationRuntimeStatus:
        row = await self.runtime_status(device_id)
        if row is None:
            row = DeviceConfigurationRuntimeStatus(device_id=device_id)
            self.session.add(row)
        row.desired_version = desired_version
        row.applied_version = applied_version
        row.apply_status = apply_status.value
        row.source = source.value
        row.last_apply_at = last_apply_at
        row.last_apply_error = last_apply_error
        await self.session.flush()
        return row


class ConfigurationAuditRepository:
    """Read the configuration lifecycle audit trail from ``audit_events``.

    The existing audit table is reused deliberately. A second audit store would
    split the operator's evidence across two places, and configuration events are
    ordinary audit events with a namespaced resource key.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_device(self, device_id: str, limit: int) -> list[AuditEvent]:
        rows = await self.session.scalars(
            select(AuditEvent)
            .where(AuditEvent.resource == config_audit_resource(device_id))
            .order_by(AuditEvent.timestamp.desc())
            .limit(limit)
        )
        return list(rows)

    async def list_all(self, limit: int) -> list[AuditEvent]:
        rows = await self.session.scalars(
            select(AuditEvent)
            .where(AuditEvent.resource.startswith(CONFIG_AUDIT_RESOURCE_PREFIX))
            .order_by(AuditEvent.timestamp.desc())
            .limit(limit)
        )
        return list(rows)

    async def recent_for_devices(self, device_ids: Sequence[str], limit: int) -> list[AuditEvent]:
        if not device_ids:
            return []
        resources = [config_audit_resource(device_id) for device_id in device_ids]
        rows = await self.session.scalars(
            select(AuditEvent)
            .where(AuditEvent.resource.in_(resources))
            .order_by(AuditEvent.timestamp.desc())
            .limit(limit)
        )
        return list(rows)
