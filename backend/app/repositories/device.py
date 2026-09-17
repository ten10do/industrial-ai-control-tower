"""Device persistence queries."""

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Device
from app.schemas.device import DeviceCreate, DeviceUpdate


class DeviceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, data: DeviceCreate) -> Device:
        device = Device(
            device_id=data.device_id,
            device_type=data.device_type,
            name=data.name,
            status=data.status,
            device_metadata=data.metadata,
        )
        self.session.add(device)
        await self.session.flush()
        return device

    async def get(self, device_id: str) -> Device | None:
        return cast(
            Device | None,
            await self.session.scalar(select(Device).where(Device.device_id == device_id)),
        )

    async def list(self, limit: int, offset: int) -> list[Device]:
        rows = await self.session.scalars(
            select(Device).order_by(Device.device_id).limit(limit).offset(offset)
        )
        return list(rows)

    async def update(self, device: Device, data: DeviceUpdate) -> Device:
        values = data.model_dump(exclude_unset=True)
        if "metadata" in values:
            values["device_metadata"] = values.pop("metadata")
        for key, value in values.items():
            setattr(device, key, value)
        await self.session.flush()
        return device
