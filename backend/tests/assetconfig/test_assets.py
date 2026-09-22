"""Asset hierarchy tests against real PostgreSQL.

The hierarchy rules are enforced in two places on purpose. The service returns a
readable error, and the database refuses illegal shapes even if the service is
bypassed. Both are tested, because a service-only guarantee is defeated by the next
code path that writes directly.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.assetconfig.errors import (
    AssetHierarchyError,
    AssetInUseError,
    AssetNotFoundError,
    DeviceNotAttachedError,
    DeviceNotFoundError,
)
from app.assetconfig.models import AssetNode, AssetType
from app.assetconfig.service import AssetService
from tests.assetconfig.conftest import FakeApplier, create_device, modbus_payload


async def _site(session: AsyncSession, name: str = "Plant A") -> AssetNode:
    return await AssetService(session).create(
        name=name,
        asset_type=AssetType.SITE,
        parent_id=None,
        description="",
        metadata={},
    )


async def _line(session: AsyncSession, parent_id: UUID, name: str = "Line 1") -> AssetNode:
    return await AssetService(session).create(
        name=name,
        asset_type=AssetType.LINE,
        parent_id=parent_id,
        description="",
        metadata={},
    )


async def test_create_site_and_line(session: AsyncSession) -> None:
    site = await _site(session)
    line = await _line(session, site.id)
    assert site.asset_type == "SITE"
    assert site.parent_id is None
    assert line.asset_type == "LINE"
    assert line.parent_id == site.id

    service = AssetService(session)
    nodes = await service.list_nodes()
    assert len(nodes) == 2


async def test_site_cannot_have_a_parent(session: AsyncSession) -> None:
    site = await _site(session)
    with pytest.raises(AssetHierarchyError):
        await AssetService(session).create(
            name="Nested site",
            asset_type=AssetType.SITE,
            parent_id=site.id,
            description="",
            metadata={},
        )


async def test_line_requires_a_parent(session: AsyncSession) -> None:
    with pytest.raises(AssetHierarchyError):
        await AssetService(session).create(
            name="Orphan line",
            asset_type=AssetType.LINE,
            parent_id=None,
            description="",
            metadata={},
        )


async def test_line_parent_must_be_a_site(session: AsyncSession) -> None:
    site = await _site(session)
    line = await _line(session, site.id)
    with pytest.raises(AssetHierarchyError):
        await _line(session, line.id, name="Nested line")


async def test_unknown_parent_is_rejected(session: AsyncSession) -> None:
    import uuid

    with pytest.raises(AssetNotFoundError):
        await _line(session, uuid.uuid4())


async def test_database_refuses_a_site_with_a_parent(session: AsyncSession) -> None:
    """Bypassing the service must not create an illegal shape."""

    site = await _site(session)
    await session.commit()
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO asset_nodes (id, name, asset_type, parent_id, description, "
                "metadata, created_at, updated_at) VALUES "
                "(gen_random_uuid(), 'illegal', 'SITE', :parent, '', '{}', now(), now())"
            ),
            {"parent": site.id},
        )
        await session.flush()


async def test_cycle_is_structurally_impossible(session: AsyncSession) -> None:
    """Only SITE nodes are roots and only LINE nodes have parents, so no cycle forms."""

    site = await _site(session)
    line = await _line(session, site.id)
    await session.commit()
    with pytest.raises(IntegrityError):
        await session.execute(
            text("UPDATE asset_nodes SET parent_id = :line WHERE id = :site"),
            {"line": line.id, "site": site.id},
        )
        await session.flush()


async def test_delete_is_blocked_while_children_exist(session: AsyncSession) -> None:
    service = AssetService(session)
    site = await _site(session)
    await _line(session, site.id)
    with pytest.raises(AssetInUseError):
        await service.delete(site.id)


async def test_delete_is_blocked_while_devices_are_attached(session: AsyncSession) -> None:
    service = AssetService(session)
    site = await _site(session)
    await create_device(session, "MOTOR-001")
    await service.attach_device(site.id, "MOTOR-001")
    with pytest.raises(AssetInUseError):
        await service.delete(site.id)


async def test_delete_after_detaching(session: AsyncSession) -> None:
    service = AssetService(session)
    site = await _site(session)
    await create_device(session, "MOTOR-001")
    await service.attach_device(site.id, "MOTOR-001")
    await service.detach_device_from(site.id, "MOTOR-001")
    await service.delete(site.id)
    assert await service.list_nodes() == []


async def test_attach_and_detach_device(session: AsyncSession) -> None:
    service = AssetService(session)
    site = await _site(session)
    line = await _line(session, site.id)
    device = await create_device(session, "MOTOR-001")

    await service.attach_device(line.id, "MOTOR-001")
    assert device.asset_node_id == line.id

    await service.detach_device_from(line.id, "MOTOR-001")
    assert device.asset_node_id is None


async def test_attach_unknown_device_is_rejected(session: AsyncSession) -> None:
    service = AssetService(session)
    site = await _site(session)
    with pytest.raises(DeviceNotFoundError):
        await service.attach_device(site.id, "MOTOR-404")


async def test_detach_from_the_wrong_node_is_rejected(session: AsyncSession) -> None:
    service = AssetService(session)
    site = await _site(session)
    other = await _site(session, name="Plant B")
    await create_device(session, "MOTOR-001")
    await service.attach_device(site.id, "MOTOR-001")
    with pytest.raises(DeviceNotAttachedError):
        await service.detach_device_from(other.id, "MOTOR-001")


async def test_tree_renders_hierarchy_and_unassigned_devices(session: AsyncSession) -> None:
    service = AssetService(session)
    site = await _site(session)
    line = await _line(session, site.id)
    await create_device(session, "MOTOR-001")
    await create_device(session, "MOTOR-002")
    await service.attach_device(line.id, "MOTOR-001")

    from app.assetconfig.service import ConfigurationService

    configs = ConfigurationService(session, FakeApplier())
    draft = await configs.create_draft("MOTOR-001", modbus_payload("MOTOR-001"), "tester")
    await configs.publish("MOTOR-001", draft.version, "tester")
    # MOTOR-002 keeps only a draft, so it has no authoritative configuration yet.
    await configs.create_draft("MOTOR-002", modbus_payload("MOTOR-002"), "tester")

    tree = await service.tree()
    assert len(tree["sites"]) == 1
    rendered_site = tree["sites"][0]
    assert rendered_site["name"] == "Plant A"
    rendered_line = rendered_site["children"][0]
    assert [device["device_id"] for device in rendered_line["devices"]] == ["MOTOR-001"]
    assert [device["device_id"] for device in tree["unassigned_devices"]] == ["MOTOR-002"]

    attached = rendered_line["devices"][0]
    assert attached["protocol"] == "modbus_tcp"
    assert attached["published_version"] == 1
    assert attached["applied_version"] == 1
    assert attached["apply_status"] == "APPLIED"
    assert attached["in_sync"] is True

    unassigned = tree["unassigned_devices"][0]
    assert unassigned["protocol"] is None
    assert unassigned["published_version"] is None
    assert unassigned["in_sync"] is False
