"""Persisted diagnosis query endpoints."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.core.errors import AppError
from app.repositories.device import DeviceRepository
from app.repositories.diagnosis import DiagnosisRepository
from app.schemas.diagnosis import DiagnosisPage, DiagnosisRead

router = APIRouter(prefix="/api/v1/devices", tags=["diagnoses"])


def _require_aware_cursor(cursor: datetime | None) -> None:
    if cursor is not None and (cursor.tzinfo is None or cursor.utcoffset() is None):
        raise AppError("INVALID_CURSOR", "'cursor' must include a timezone.", 422)


@router.get("/{device_id}/diagnoses", response_model=DiagnosisPage)
async def list_diagnoses(
    device_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    cursor: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> DiagnosisPage:
    _require_aware_cursor(cursor)
    if await DeviceRepository(session).get(device_id) is None:
        raise AppError("DEVICE_NOT_FOUND", f"Device '{device_id}' was not found.", 404)
    rows = await DiagnosisRepository(session).list(device_id, cursor=cursor, limit=limit + 1)
    has_more = len(rows) > limit
    items = rows[:limit]
    return DiagnosisPage(
        items=[DiagnosisRead.model_validate(row) for row in items],
        next_cursor=items[-1].created_at if has_more else None,
    )


@router.get("/{device_id}/diagnoses/latest", response_model=DiagnosisRead)
async def latest_diagnosis(
    device_id: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> DiagnosisRead:
    if await DeviceRepository(session).get(device_id) is None:
        raise AppError("DEVICE_NOT_FOUND", f"Device '{device_id}' was not found.", 404)
    diagnosis = await DiagnosisRepository(session).latest(device_id)
    if diagnosis is None:
        raise AppError("DIAGNOSIS_NOT_FOUND", "No diagnosis is available for this device.", 404)
    return DiagnosisRead.model_validate(diagnosis)
