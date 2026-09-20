"""Diagnosis persistence and cursor queries."""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.runtime import DiagnosisPrediction
from app.models import Diagnosis


class DiagnosisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_prediction(self, prediction: DiagnosisPrediction, trace_id: str) -> Diagnosis:
        diagnosis = Diagnosis(
            device_id=prediction.device_id,
            window_start=datetime.fromisoformat(prediction.window_start),
            window_end=datetime.fromisoformat(prediction.window_end),
            status=prediction.status,
            fault_type=prediction.fault_type,
            anomaly_score=prediction.anomaly_score,
            confidence=prediction.confidence,
            severity=prediction.severity,
            evidence=[item.model_dump() for item in prediction.evidence],
            model_version=prediction.model_version,
            feature_version=prediction.feature_version,
            trace_id=trace_id,
        )
        self.session.add(diagnosis)
        await self.session.flush()
        return diagnosis

    async def create_failed(
        self,
        *,
        device_id: str,
        window_start: datetime,
        window_end: datetime,
        trace_id: str,
        reason: str,
    ) -> Diagnosis:
        diagnosis = Diagnosis(
            device_id=device_id,
            window_start=window_start,
            window_end=window_end,
            status="FAILED",
            severity=None,
            evidence=[],
            trace_id=trace_id,
            payload={"reason": reason},
        )
        self.session.add(diagnosis)
        await self.session.flush()
        return diagnosis

    async def list(self, device_id: str, *, cursor: datetime | None, limit: int) -> list[Diagnosis]:
        query: Select[tuple[Diagnosis]] = select(Diagnosis).where(Diagnosis.device_id == device_id)
        if cursor is not None:
            query = query.where(Diagnosis.created_at < cursor)
        rows = await self.session.scalars(query.order_by(Diagnosis.created_at.desc()).limit(limit))
        return list(rows)

    async def latest(self, device_id: str) -> Diagnosis | None:
        return cast(
            Diagnosis | None,
            await self.session.scalar(
                select(Diagnosis)
                .where(Diagnosis.device_id == device_id)
                .order_by(Diagnosis.created_at.desc())
                .limit(1)
            ),
        )

    async def get(self, diagnosis_id: UUID, device_id: str) -> Diagnosis | None:
        return cast(
            Diagnosis | None,
            await self.session.scalar(
                select(Diagnosis).where(
                    Diagnosis.id == diagnosis_id, Diagnosis.device_id == device_id
                )
            ),
        )
