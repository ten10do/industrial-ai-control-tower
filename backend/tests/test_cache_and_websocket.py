"""Unit tests for latest-only cache and bounded WebSocket semantics."""

from typing import cast
from uuid import uuid4

import pytest
from fastapi import WebSocket
from redis.asyncio import Redis

from app.infrastructure.redis.latest import LatestTelemetryCache
from app.schemas.telemetry import TelemetryRead
from app.websocket.manager import WebSocketManager


def telemetry(timestamp: str) -> TelemetryRead:
    return TelemetryRead.model_validate(
        {
            "id": uuid4(),
            "schema_version": "1.0",
            "timestamp": timestamp,
            "device_id": "MOTOR-001",
            "temperature_c": 60,
            "bearing_temperature_c": 63,
            "vibration_mm_s": 2,
            "current_a": 5,
            "voltage_v": 380,
            "rpm": 1440,
            "load_pct": 50,
            "power_kw": 3,
            "operating_state": "RUNNING",
            "fault_state": "NORMAL",
            "ingested_at": timestamp,
        }
    )


class FakeRedis:
    def __init__(self) -> None:
        self.epoch: float | None = None
        self.payload: str | None = None

    async def eval(self, script: str, keys: int, key: str, epoch: float, payload: str) -> int:
        if self.epoch is not None and self.epoch >= float(epoch):
            return 0
        self.epoch = float(epoch)
        self.payload = payload
        return 1

    async def hget(self, key: str, field: str) -> str | None:
        return self.payload


@pytest.mark.asyncio
async def test_stale_telemetry_cannot_replace_latest_cache() -> None:
    fake = FakeRedis()
    cache = LatestTelemetryCache(cast(Redis, fake))
    newest = telemetry("2026-09-17T08:00:02Z")
    older = telemetry("2026-09-17T08:00:01Z")
    assert await cache.set_if_newer(newest) is True
    assert await cache.set_if_newer(older) is False
    assert await cache.get("MOTOR-001") == newest


class FakeWebSocket:
    async def accept(self) -> None:
        return None


@pytest.mark.asyncio
async def test_slow_websocket_client_keeps_only_latest_value() -> None:
    manager = WebSocketManager(queue_size=1)
    websocket = cast(WebSocket, FakeWebSocket())
    queue = await manager.connect("MOTOR-001", websocket)
    await manager.broadcast("MOTOR-001", "first")
    await manager.broadcast("MOTOR-001", "second")
    assert queue.qsize() == 1
    assert queue.get_nowait() == "second"
    await manager.disconnect("MOTOR-001", websocket)
