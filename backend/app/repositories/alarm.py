"""Alarm persistence queries."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alarm


class AlarmRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        device_id: str,
        telemetry_id: UUID,
        rule_id: str,
        severity: str,
        message: str,
    ) -> Alarm:
        alarm = Alarm(
            device_id=device_id,
            telemetry_id=telemetry_id,
            rule_id=rule_id,
            severity=severity,
            message=message,
        )
        self.session.add(alarm)
        await self.session.flush()
        return alarm

    async def list(self, device_id: str | None, limit: int) -> list[Alarm]:
        query = select(Alarm)
        if device_id is not None:
            query = query.where(Alarm.device_id == device_id)
        rows = await self.session.scalars(query.order_by(Alarm.started_at.desc()).limit(limit))
        return list(rows)
