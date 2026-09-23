"""Telemetry ingestion, validation, caching, alarm rules, and fan-out."""

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import trace_id_context
from app.core.errors import AppError
from app.incidents.service import AlarmLifecycleService
from app.infrastructure.redis.latest import LatestTelemetryCache
from app.models import Device
from app.repositories.audit import AuditRepository
from app.repositories.device import DeviceRepository
from app.repositories.telemetry import TelemetryRepository
from app.schemas.telemetry import TelemetryIn, TelemetryRead
from app.services.diagnosis import OnlineDiagnosisCoordinator
from app.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IngestionCounters:
    consumed: int = 0
    persisted: int = 0
    duplicates: int = 0
    rejected: int = 0


@dataclass(slots=True)
class IngestionResult:
    status: str
    telemetry: TelemetryRead | None = None


class TelemetryService:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis,
        websocket_manager: WebSocketManager,
        counters: IngestionCounters,
        diagnosis: OnlineDiagnosisCoordinator | None = None,
    ) -> None:
        self.session = session
        self.telemetry = TelemetryRepository(session)
        self.devices = DeviceRepository(session)
        self.alarms = AlarmLifecycleService(session)
        self.audit = AuditRepository(session)
        self.cache = LatestTelemetryCache(redis)
        self.websocket_manager = websocket_manager
        self.counters = counters
        self.diagnosis = diagnosis

    async def ingest_payload(self, topic: str, payload: bytes) -> IngestionResult:
        self.counters.consumed += 1
        trace_id = str(uuid4())
        token = trace_id_context.set(trace_id)
        try:
            try:
                raw: Any = json.loads(payload)
                data = TelemetryIn.model_validate(raw)
            except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
                await self._reject(topic, "INVALID_TELEMETRY", type(exc).__name__)
                return IngestionResult("REJECTED")

            topic_device_id = self._topic_device_id(topic)
            if topic_device_id != data.device_id:
                await self._reject(topic, "DEVICE_TOPIC_MISMATCH", data.device_id)
                return IngestionResult("REJECTED")

            device = await self.devices.get(data.device_id)
            if device is None:
                await self._reject(topic, "UNKNOWN_DEVICE", data.device_id)
                return IngestionResult("REJECTED")

            model = await self.telemetry.insert_once(data)
            if model is None:
                self.counters.duplicates += 1
                await self.session.rollback()
                logger.info("telemetry_duplicate", extra={"device_id": data.device_id})
                return IngestionResult("DUPLICATE")

            alarm_count = await self._apply_alarm_rules(device, model.id, data)
            await self.session.commit()
            response = TelemetryRead.model_validate(model)
            self.counters.persisted += 1
            is_latest = await self._publish_latest(response)
            if is_latest and self.diagnosis is not None:
                await self.diagnosis.handle(response)
            logger.info(
                "telemetry_persisted",
                extra={"device_id": data.device_id, "alarm_count": alarm_count},
            )
            return IngestionResult("PERSISTED", response)
        finally:
            trace_id_context.reset(token)

    async def latest(self, device_id: str) -> TelemetryRead:
        if await self.devices.get(device_id) is None:
            raise AppError("DEVICE_NOT_FOUND", f"Device '{device_id}' was not found.", 404)
        try:
            cached = await self.cache.get(device_id)
            if cached is not None:
                return cached
        except Exception:
            logger.exception("redis_latest_read_failed", extra={"device_id": device_id})
        model = await self.telemetry.latest(device_id)
        if model is None:
            raise AppError("TELEMETRY_NOT_FOUND", "No telemetry is available for this device.", 404)
        response = TelemetryRead.model_validate(model)
        try:
            await self.cache.set_if_newer(response)
        except Exception:
            logger.exception("redis_latest_rebuild_failed", extra={"device_id": device_id})
        return response

    async def _publish_latest(self, telemetry: TelemetryRead) -> bool:
        try:
            is_latest = await self.cache.set_if_newer(telemetry)
        except Exception:
            logger.exception("redis_latest_write_failed", extra={"device_id": telemetry.device_id})
            latest = await self.telemetry.latest(telemetry.device_id)
            is_latest = latest is not None and latest.id == telemetry.id
        if is_latest:
            await self.websocket_manager.broadcast(telemetry.device_id, telemetry.model_dump_json())
        return is_latest

    async def _apply_alarm_rules(
        self, device: Device, telemetry_id: UUID, data: TelemetryIn
    ) -> int:
        """Evaluate the rule registry and fold the breaches into alarm state.

        The rule set is data now rather than two string literals, so a threshold
        change no longer needs a release. What did not change is the position of
        this call: it still runs before the ingestion commit, so a persisted
        measurement cannot exist without the alarm it raised.

        A rule fault is contained rather than propagated. Losing a raw
        measurement is the more serious failure of the two, so a broken rule
        produces a missing alarm and an auditable record instead of a rejected
        sample. The savepoint is what makes that containment honest: only the
        alarm work is rolled back, and the telemetry row still commits.
        """

        try:
            async with self.session.begin_nested():
                touched = await self.alarms.record_breaches(
                    device_id=device.device_id,
                    device_type=device.device_type,
                    telemetry_id=telemetry_id,
                    payload=data.model_dump(),
                    triggered_at=data.timestamp,
                )
        except Exception:
            logger.exception("alarm_evaluation_failed", extra={"device_id": device.device_id})
            self.audit.add(
                trace_id=trace_id_context.get(),
                action="ALARM_EVALUATION_FAILED",
                resource=device.device_id,
                status="FAILED",
                details={"reason": "rule evaluation raised", "telemetry_id": str(telemetry_id)},
            )
            return 0
        return len(touched)

    async def _reject(self, topic: str, reason: str, detail: str) -> None:
        self.counters.rejected += 1
        self.audit.add(
            trace_id=trace_id_context.get(),
            action="TELEMETRY_REJECTED",
            resource=topic,
            status="FAILED",
            details={"reason": reason, "detail": detail},
        )
        await self.session.commit()
        logger.warning("telemetry_rejected", extra={"topic": topic, "reason": reason})

    @staticmethod
    def _topic_device_id(topic: str) -> str:
        parts = topic.split("/")
        if len(parts) != 4 or parts[0] != "industrial" or parts[1] != "devices":
            return ""
        return parts[2]
