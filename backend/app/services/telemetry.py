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
from app.infrastructure.redis.latest import LatestTelemetryCache
from app.repositories.alarm import AlarmRepository
from app.repositories.audit import AuditRepository
from app.repositories.device import DeviceRepository
from app.repositories.telemetry import TelemetryRepository
from app.schemas.telemetry import TelemetryIn, TelemetryRead
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
    ) -> None:
        self.session = session
        self.telemetry = TelemetryRepository(session)
        self.devices = DeviceRepository(session)
        self.alarms = AlarmRepository(session)
        self.audit = AuditRepository(session)
        self.cache = LatestTelemetryCache(redis)
        self.websocket_manager = websocket_manager
        self.counters = counters

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

            if await self.devices.get(data.device_id) is None:
                await self._reject(topic, "UNKNOWN_DEVICE", data.device_id)
                return IngestionResult("REJECTED")

            model = await self.telemetry.insert_once(data)
            if model is None:
                self.counters.duplicates += 1
                await self.session.rollback()
                logger.info("telemetry_duplicate", extra={"device_id": data.device_id})
                return IngestionResult("DUPLICATE")

            alarm_count = await self._apply_alarm_rules(model.id, data)
            await self.session.commit()
            response = TelemetryRead.model_validate(model)
            self.counters.persisted += 1
            await self._publish_latest(response)
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

    async def _publish_latest(self, telemetry: TelemetryRead) -> None:
        try:
            is_latest = await self.cache.set_if_newer(telemetry)
        except Exception:
            logger.exception("redis_latest_write_failed", extra={"device_id": telemetry.device_id})
            latest = await self.telemetry.latest(telemetry.device_id)
            is_latest = latest is not None and latest.id == telemetry.id
        if is_latest:
            await self.websocket_manager.broadcast(telemetry.device_id, telemetry.model_dump_json())

    async def _apply_alarm_rules(self, telemetry_id: UUID, data: TelemetryIn) -> int:
        rules: list[tuple[str, str, str]] = []
        if data.temperature_c > 90:
            rules.append(("HIGH_TEMPERATURE", "CRITICAL", "Temperature exceeds 90 °C."))
        if data.vibration_mm_s > 7:
            rules.append(("HIGH_VIBRATION", "WARNING", "Vibration exceeds 7 mm/s RMS."))
        for rule_id, severity, message in rules:
            await self.alarms.create(
                device_id=data.device_id,
                telemetry_id=telemetry_id,
                rule_id=rule_id,
                severity=severity,
                message=message,
            )
            self.audit.add(
                trace_id=trace_id_context.get(),
                action="ALARM_CREATED",
                resource=data.device_id,
                status="SUCCESS",
                details={"rule_id": rule_id},
            )
        return len(rules)

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
