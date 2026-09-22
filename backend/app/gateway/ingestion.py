"""Bridge from gateway samples to the existing ingestion boundary.

The gateway does not introduce a second ingestion pipeline. Every polled sample is
normalized into the canonical contract and submitted to
``TelemetryService.ingest_payload``, which is the same entry point the MQTT consumer
uses. Device registration checks, deduplication, alarm rules, the Redis latest-value
cache, WebSocket fan-out, and online diagnosis therefore behave identically for
polled and pushed protocols.

The gateway is read-only towards the process it observes: it verifies that a device
is registered, and it never creates or mutates device rows.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Protocol

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from adapters.models import UnifiedTelemetry
from app.gateway.models import DeviceStateDefinition
from app.gateway.normalizer import to_canonical_body
from app.repositories.device import DeviceRepository
from app.services.diagnosis import OnlineDiagnosisCoordinator
from app.services.telemetry import IngestionCounters, TelemetryService
from app.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)

PERSISTED: str = "PERSISTED"
DUPLICATE: str = "DUPLICATE"
REJECTED: str = "REJECTED"


class IngestionOutcome(StrEnum):
    """Result of handing one sample to the ingestion boundary."""

    PERSISTED = PERSISTED
    DUPLICATE = DUPLICATE
    REJECTED = REJECTED


def telemetry_topic(device_id: str) -> str:
    """Return the canonical ingestion topic for a device.

    The ingestion contract parses ``industrial/devices/<device_id>/<suffix>``.
    """

    return f"industrial/devices/{device_id}/telemetry"


class TelemetrySink(Protocol):
    """Submit one normalized adapter sample for ingestion."""

    async def publish(
        self, telemetry: UnifiedTelemetry, definition: DeviceStateDefinition
    ) -> IngestionOutcome: ...


class RegistrationChecker(Protocol):
    """Report whether a device is registered in the operational database."""

    async def exists(self, device_id: str) -> bool: ...


class GatewayIngestionSink:
    """Submit gateway samples through ``TelemetryService.ingest_payload``."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        redis: Redis,
        websocket_manager: WebSocketManager,
        counters: IngestionCounters,
        diagnosis: OnlineDiagnosisCoordinator | None = None,
    ) -> None:
        self._sessions = sessions
        self._redis = redis
        self._websocket_manager = websocket_manager
        self._counters = counters
        self._diagnosis = diagnosis

    async def publish(
        self, telemetry: UnifiedTelemetry, definition: DeviceStateDefinition
    ) -> IngestionOutcome:
        body = to_canonical_body(telemetry, definition)
        topic = telemetry_topic(telemetry.device_id)
        async with self._sessions() as session:
            service = TelemetryService(
                session,
                self._redis,
                self._websocket_manager,
                self._counters,
                self._diagnosis,
            )
            result = await service.ingest_payload(topic, body)
        outcome = _OUTCOMES.get(result.status, IngestionOutcome.REJECTED)
        if outcome is IngestionOutcome.REJECTED:
            logger.warning(
                "gateway_sample_rejected",
                extra={"device_id": telemetry.device_id, "topic": topic},
            )
        return outcome


_OUTCOMES: dict[str, IngestionOutcome] = {
    PERSISTED: IngestionOutcome.PERSISTED,
    DUPLICATE: IngestionOutcome.DUPLICATE,
    REJECTED: IngestionOutcome.REJECTED,
}


class DeviceRegistrationChecker:
    """Read-only device registration lookup."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def exists(self, device_id: str) -> bool:
        async with self._sessions() as session:
            return await DeviceRepository(session).get(device_id) is not None
