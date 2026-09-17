"""Telemetry history and latest-state endpoints."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_redis, get_session, get_websocket_manager
from app.core.errors import AppError
from app.repositories.device import DeviceRepository
from app.repositories.telemetry import TelemetryRepository
from app.schemas.telemetry import TelemetryPage, TelemetryRead
from app.services.telemetry import IngestionCounters, TelemetryService
from app.websocket.manager import WebSocketManager

router = APIRouter(prefix="/api/v1/devices", tags=["telemetry"])


def _require_aware(value: datetime | None, name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise AppError("INVALID_TIME_RANGE", f"'{name}' must include a timezone.", 422)


@router.get("/{device_id}/telemetry", response_model=TelemetryPage)
async def telemetry_history(
    device_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    start: datetime | None = None,
    end: datetime | None = None,
    cursor: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> TelemetryPage:
    _require_aware(start, "start")
    _require_aware(end, "end")
    _require_aware(cursor, "cursor")
    if start is not None and end is not None and start > end:
        raise AppError("INVALID_TIME_RANGE", "'start' must not be after 'end'.", 422)
    if await DeviceRepository(session).get(device_id) is None:
        raise AppError("DEVICE_NOT_FOUND", f"Device '{device_id}' was not found.", 404)
    rows = await TelemetryRepository(session).history(
        device_id, start=start, end=end, cursor=cursor, limit=limit + 1
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    return TelemetryPage(
        items=[TelemetryRead.model_validate(row) for row in items],
        next_cursor=items[-1].timestamp if has_more else None,
    )


@router.get("/{device_id}/telemetry/latest", response_model=TelemetryRead)
async def latest_telemetry(
    device_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    websocket_manager: Annotated[WebSocketManager, Depends(get_websocket_manager)],
) -> TelemetryRead:
    return await TelemetryService(session, redis, websocket_manager, IngestionCounters()).latest(
        device_id
    )
