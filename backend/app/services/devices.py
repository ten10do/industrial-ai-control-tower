"""Device registration and lifecycle service."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import trace_id_context
from app.core.errors import AppError
from app.models import Device
from app.repositories.audit import AuditRepository
from app.repositories.device import DeviceRepository
from app.schemas.device import DeviceCreate, DeviceUpdate


class DeviceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.devices = DeviceRepository(session)
        self.audit = AuditRepository(session)

    async def create(self, data: DeviceCreate) -> Device:
        try:
            device = await self.devices.create(data)
            self.audit.add(
                trace_id=trace_id_context.get(),
                action="DEVICE_CREATED",
                resource=data.device_id,
                status="SUCCESS",
            )
            await self.session.commit()
            return device
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppError("DEVICE_ALREADY_EXISTS", "Device already exists.", 409) from exc

    async def get(self, device_id: str) -> Device:
        device = await self.devices.get(device_id)
        if device is None:
            raise AppError("DEVICE_NOT_FOUND", f"Device '{device_id}' was not found.", 404)
        return device

    async def list(self, limit: int, offset: int) -> list[Device]:
        return await self.devices.list(limit, offset)

    async def update(self, device_id: str, data: DeviceUpdate) -> Device:
        device = await self.get(device_id)
        await self.devices.update(device, data)
        self.audit.add(
            trace_id=trace_id_context.get(),
            action="DEVICE_UPDATED",
            resource=device_id,
            status="SUCCESS",
            details={"fields": sorted(data.model_dump(exclude_unset=True))},
        )
        await self.session.commit()
        return device
