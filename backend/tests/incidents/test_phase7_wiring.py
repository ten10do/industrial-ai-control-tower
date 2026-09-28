"""Regression coverage for the two Phase 7 production wiring gaps."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ml.runtime import DiagnosisPrediction
from app.models import Diagnosis, Incident
from app.services.diagnosis import OnlineDiagnosisCoordinator
from app.services.telemetry import IngestionCounters, TelemetryService
from app.websocket.manager import WebSocketManager
from tests.incidents.conftest import create_device, seed_rule, telemetry_payload, utc


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    async def eval(self, script: str, keys: int, key: str, epoch: float, payload: str) -> int:
        current = self.values.get(f"{key}:epoch")
        if current is not None and float(current) >= epoch:
            return 0
        self.values[f"{key}:epoch"] = str(epoch).encode()
        self.values[f"{key}:payload"] = payload.encode()
        return 1

    async def hget(self, key: str, field: str) -> bytes | None:
        return self.values.get(f"{key}:{field}")


class FakeExtractor:
    window_size = 2


class FaultRuntime:
    extractor = FakeExtractor()
    bundle = {"inference_stride": 1}

    def predict(self, window: Any) -> DiagnosisPrediction:
        return DiagnosisPrediction(
            device_id=window.device_id,
            window_start=window.start.isoformat(),
            window_end=window.end.isoformat(),
            status="FAULT",
            fault_type="BEARING_WEAR",
            anomaly_score=0.99,
            confidence=0.98,
            severity="CRITICAL",
            evidence=[],
            model_version="diagnosis-v1.1",
            feature_version="features-v1",
        )


@pytest.mark.asyncio
async def test_ingestion_correlates_alarm_and_links_online_diagnosis(
    session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await create_device(session, "MOTOR-PH7")
    await seed_rule(
        session,
        "phase7_temperature",
        signal_name="temperature",
        threshold=50.0,
        severity="CRITICAL",
    )
    await session.commit()
    diagnosis = OnlineDiagnosisCoordinator(FaultRuntime(), sessions)  # type: ignore[arg-type]
    service = TelemetryService(
        session,
        FakeRedis(),  # type: ignore[arg-type]
        WebSocketManager(),
        IngestionCounters(),
        diagnosis,
    )
    first_at = utc(2026, 9, 28, 10, 0, 0)
    for offset in range(2):
        payload = telemetry_payload(
            "MOTOR-PH7",
            timestamp=first_at + timedelta(seconds=offset),
            temperature_c=95.0,
        )
        result = await service.ingest_payload(
            "industrial/devices/MOTOR-PH7/telemetry",
            json.dumps(payload).encode(),
        )
        assert result.status == "PERSISTED"

    assert int(await session.scalar(select(func.count()).select_from(Incident)) or 0) == 1
    incident = await session.scalar(select(Incident))
    row = await session.scalar(select(Diagnosis).order_by(Diagnosis.created_at.desc()))
    assert incident is not None
    assert row is not None
    assert row.incident_id == incident.id
    assert row.fault_type == "BEARING_WEAR"
