"""Read-only Phase 2 alarm API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.repositories.alarm import AlarmRepository
from app.schemas.alarm import AlarmRead

router = APIRouter(prefix="/api/v1/alarms", tags=["alarms"])


@router.get("", response_model=list[AlarmRead])
async def list_alarms(
    session: Annotated[AsyncSession, Depends(get_session)],
    device_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AlarmRead]:
    alarms = await AlarmRepository(session).list(device_id, limit)
    return [AlarmRead.model_validate(alarm) for alarm in alarms]
