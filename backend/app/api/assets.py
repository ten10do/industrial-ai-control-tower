"""Asset hierarchy endpoints.

The asset tree is a minimal location hierarchy. Device identity still lives in the
existing ``devices`` table, so this router can attach and detach devices but can
never create, rename, or delete a device master record.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.assetconfig.contracts import AssetNodeCreate, AssetNodeRead, AssetTreeRead
from app.assetconfig.models import AssetNode
from app.assetconfig.service import AssetService

router = APIRouter(tags=["assets"])


def _read(node: AssetNode, device_count: int = 0) -> AssetNodeRead:
    model = AssetNodeRead.model_validate(node)
    model.device_count = device_count
    return model


@router.get("/assets", response_model=list[AssetNodeRead])
async def list_assets(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AssetNodeRead]:
    service = AssetService(session)
    counts = await service.assets.device_counts()
    return [_read(node, counts.get(node.id, 0)) for node in await service.list_nodes()]


@router.get("/assets/tree", response_model=AssetTreeRead)
async def asset_tree(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssetTreeRead:
    return AssetTreeRead.model_validate(await AssetService(session).tree())


@router.post("/assets", response_model=AssetNodeRead, status_code=status.HTTP_201_CREATED)
async def create_asset(
    data: AssetNodeCreate, session: Annotated[AsyncSession, Depends(get_session)]
) -> AssetNodeRead:
    node = await AssetService(session).create(
        name=data.name,
        asset_type=data.asset_type,
        parent_id=data.parent_id,
        description=data.description,
        metadata=data.metadata,
    )
    return _read(node)


@router.get("/assets/{asset_id}", response_model=AssetNodeRead)
async def get_asset(
    asset_id: UUID, session: Annotated[AsyncSession, Depends(get_session)]
) -> AssetNodeRead:
    service = AssetService(session)
    node = await service.get(asset_id)
    return _read(node, await service.assets.device_count(node.id))


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: UUID, session: Annotated[AsyncSession, Depends(get_session)]
) -> None:
    await AssetService(session).delete(asset_id)


@router.put("/assets/{asset_id}/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def attach_device(
    asset_id: UUID, device_id: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> None:
    await AssetService(session).attach_device(asset_id, device_id)


@router.delete("/assets/{asset_id}/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach_device(
    asset_id: UUID, device_id: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> None:
    await AssetService(session).detach_device_from(asset_id, device_id)
