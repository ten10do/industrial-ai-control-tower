"""Bounded online windowing, inference, persistence, warmup, and metrics."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.context import trace_id_context
from app.ml.features import TelemetryWindow, WindowSample
from app.ml.runtime import ModelRuntime
from app.repositories.audit import AuditRepository
from app.repositories.device import DeviceRepository
from app.repositories.diagnosis import DiagnosisRepository
from app.repositories.telemetry import TelemetryRepository
from app.schemas.telemetry import TelemetryRead

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DiagnosisMetrics:
    inference_count: int = 0
    failure_count: int = 0
    uncertain_count: int = 0
    total_latency_ms: float = 0.0
    prediction_distribution: Counter[str] = field(default_factory=Counter)


class OnlineDiagnosisCoordinator:
    """Maintain one bounded buffer per device and run the frozen model at a stride."""

    def __init__(
        self,
        runtime: ModelRuntime,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self.runtime = runtime
        self.sessions = sessions
        self.window_size = runtime.extractor.window_size
        self.stride = int(runtime.bundle["inference_stride"])
        self.buffers: dict[str, deque[TelemetryRead]] = defaultdict(
            lambda: deque(maxlen=self.window_size)
        )
        self.samples_since_inference: Counter[str] = Counter()
        self.metrics = DiagnosisMetrics()

    async def warmup(self) -> dict[str, int]:
        """Restore bounded windows from PostgreSQL without producing diagnoses."""
        warmed: dict[str, int] = {}
        async with self.sessions() as session:
            devices = await DeviceRepository(session).list(limit=5_000, offset=0)
            telemetry = TelemetryRepository(session)
            for device in devices:
                rows = await telemetry.recent_window(device.device_id, self.window_size)
                self.buffers[device.device_id].extend(
                    TelemetryRead.model_validate(row) for row in rows
                )
                self.samples_since_inference[device.device_id] = 0
                warmed[device.device_id] = len(rows)
        logger.info("diagnosis_windows_warmed", extra={"device_count": len(warmed)})
        return warmed

    async def handle(self, telemetry: TelemetryRead) -> None:
        buffer = self.buffers[telemetry.device_id]
        if buffer and telemetry.timestamp <= buffer[-1].timestamp:
            return
        buffer.append(telemetry)
        self.samples_since_inference[telemetry.device_id] += 1
        if len(buffer) < self.window_size:
            return
        if self.samples_since_inference[telemetry.device_id] < self.stride:
            return
        self.samples_since_inference[telemetry.device_id] = 0
        samples = [WindowSample.model_validate(item, from_attributes=True) for item in buffer]
        window = TelemetryWindow(device_id=telemetry.device_id, samples=samples)
        started = time.perf_counter()
        trace_id = trace_id_context.get()
        try:
            prediction = await asyncio.to_thread(self.runtime.predict, window)
            latency_ms = (time.perf_counter() - started) * 1000.0
            async with self.sessions() as session:
                await DiagnosisRepository(session).create_prediction(prediction, trace_id)
                AuditRepository(session).add(
                    trace_id=trace_id,
                    action="DIAGNOSIS_CREATED",
                    resource=telemetry.device_id,
                    status="SUCCESS",
                    details={
                        "diagnosis_status": prediction.status,
                        "model_version": prediction.model_version,
                    },
                )
                await session.commit()
            self.metrics.inference_count += 1
            self.metrics.total_latency_ms += latency_ms
            if prediction.status == "UNCERTAIN":
                self.metrics.uncertain_count += 1
            self.metrics.prediction_distribution[prediction.fault_type or "UNCERTAIN"] += 1
            logger.info(
                "diagnosis_inference_completed"
                if prediction.status != "UNCERTAIN"
                else "diagnosis_inference_uncertain",
                extra={
                    "device_id": telemetry.device_id,
                    "model_version": prediction.model_version,
                    "diagnosis_status": prediction.status,
                    "latency_ms": round(latency_ms, 3),
                },
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            self.metrics.failure_count += 1
            self.metrics.total_latency_ms += latency_ms
            async with self.sessions() as session:
                await DiagnosisRepository(session).create_failed(
                    device_id=telemetry.device_id,
                    window_start=window.start,
                    window_end=window.end,
                    trace_id=trace_id,
                    reason=type(exc).__name__,
                )
                AuditRepository(session).add(
                    trace_id=trace_id,
                    action="DIAGNOSIS_FAILED",
                    resource=telemetry.device_id,
                    status="FAILED",
                    details={"error_type": type(exc).__name__},
                )
                await session.commit()
            logger.exception(
                "diagnosis_inference_failed",
                extra={"device_id": telemetry.device_id, "latency_ms": round(latency_ms, 3)},
            )
