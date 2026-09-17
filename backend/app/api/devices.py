"""Device management endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.schemas.device import DeviceCreate, DeviceRead, DeviceUpdate
from app.services.devices import DeviceService

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


@router.post("", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
async def create_device(
    data: DeviceCreate, session: Annotated[AsyncSession, Depends(get_session)]
) -> DeviceRead:
    return DeviceRead.model_validate(await DeviceService(session).create(data))


@router.get("", response_model=list[DeviceRead])
async def list_devices(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DeviceRead]:
    devices = await DeviceService(session).list(limit, offset)
    return [DeviceRead.model_validate(device) for device in devices]


@router.get("/{device_id}", response_model=DeviceRead)
async def get_device(
    device_id: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> DeviceRead:
    return DeviceRead.model_validate(await DeviceService(session).get(device_id))


@router.patch("/{device_id}", response_model=DeviceRead)
async def update_device(
    device_id: str,
    data: DeviceUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceRead:
    return DeviceRead.model_validate(await DeviceService(session).update(device_id, data))
