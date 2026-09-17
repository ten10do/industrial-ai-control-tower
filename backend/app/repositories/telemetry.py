"""Telemetry persistence and bounded history queries."""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Telemetry
from app.schemas.telemetry import TelemetryIn


class TelemetryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert_once(self, data: TelemetryIn) -> Telemetry | None:
        values = data.model_dump()
        statement = (
            insert(Telemetry)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["device_id", "timestamp"])
            .returning(Telemetry.id)
        )
        telemetry_id: UUID | None = await self.session.scalar(statement)
        if telemetry_id is None:
            return None
        return cast(Telemetry | None, await self.session.get(Telemetry, telemetry_id))

    async def latest(self, device_id: str) -> Telemetry | None:
        return cast(
            Telemetry | None,
            await self.session.scalar(
                select(Telemetry)
                .where(Telemetry.device_id == device_id)
                .order_by(Telemetry.timestamp.desc())
                .limit(1)
            ),
        )

    async def history(
        self,
        device_id: str,
        *,
        start: datetime | None,
        end: datetime | None,
        cursor: datetime | None,
        limit: int,
    ) -> list[Telemetry]:
        query: Select[tuple[Telemetry]] = select(Telemetry).where(Telemetry.device_id == device_id)
        if start is not None:
            query = query.where(Telemetry.timestamp >= start)
        if end is not None:
            query = query.where(Telemetry.timestamp <= end)
        if cursor is not None:
            query = query.where(Telemetry.timestamp < cursor)
        rows = await self.session.scalars(query.order_by(Telemetry.timestamp.desc()).limit(limit))
        return list(rows)
