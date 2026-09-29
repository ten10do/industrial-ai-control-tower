"""Real MQTT disconnect/reconnect injection for the Phase 7 harness."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import aiomqtt
import httpx
from redis.asyncio import Redis
from simulator.models import Telemetry  # type: ignore[import-not-found]
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.gateway.gateway import IndustrialProtocolGateway
from app.gateway.ingestion import DeviceRegistrationChecker, GatewayIngestionSink
from app.gateway.models import DeviceDefinition, DeviceState
from app.gateway.registry import DeviceRegistry
from app.infrastructure.mqtt.consumer import MqttTelemetryConsumer
from app.models import Telemetry as TelemetryRow
from app.services.diagnosis import OnlineDiagnosisCoordinator
from app.services.telemetry import IngestionCounters
from app.websocket.manager import WebSocketManager


@dataclass(frozen=True, slots=True)
class MqttFailureObservation:
    """Facts proving that the production MQTT consumer recovered."""

    disconnected: bool
    reconnected: bool
    gateway_degraded: bool
    gateway_recovered: bool


class MqttFailureHarness:
    """Drive the production MQTT consumer through a disposable broker proxy."""

    def __init__(
        self,
        *,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        redis: Redis,
        diagnosis: OnlineDiagnosisCoordinator,
        websocket_manager: WebSocketManager,
        counters: IngestionCounters,
        control_url: str,
        proxy_name: str,
        listen: str,
        upstream: str,
        broker_host: str,
        broker_port: int,
    ) -> None:
        self.settings = settings.model_copy(
            update={
                "mqtt_host": broker_host,
                "mqtt_port": broker_port,
                "mqtt_topic": "industrial/devices/+/telemetry",
            }
        )
        self.sessions = sessions
        self.redis = redis
        self.diagnosis = diagnosis
        self.websocket_manager = websocket_manager
        self.counters = counters
        self.control_url = control_url.rstrip("/")
        self.proxy_name = proxy_name
        self.listen = listen
        self.upstream = upstream

    async def ingest(
        self,
        *,
        device_id: str,
        samples: list[Telemetry],
    ) -> MqttFailureObservation:
        """Publish through MQTT, cut the connection, restore it, and finish ingestion."""

        await self._prepare_proxy()
        consumer = MqttTelemetryConsumer(
            self.settings,
            self.sessions,
            self.redis,
            self.websocket_manager,
            self.counters,
            self.diagnosis,
        )
        gateway = self._gateway(device_id, consumer)
        consumer.start()
        await gateway.start()
        try:
            await self._wait_for(lambda: consumer.connected, "MQTT consumer did not connect")
            split = max(1, len(samples) // 2)
            await self._publish(device_id, samples[:split])
            await self._wait_for_count(device_id, split)

            await self._set_proxy_enabled(False)
            await self._wait_for(
                lambda: not consumer.connected,
                "MQTT consumer did not observe the controlled disconnect",
            )
            disconnected = not consumer.connected
            gateway_degraded = gateway.status(device_id).state is DeviceState.DEGRADED

            await self._set_proxy_enabled(True)
            await self._wait_for(lambda: consumer.connected, "MQTT consumer did not reconnect")
            reconnected = consumer.connected
            gateway_recovered = gateway.status(device_id).state is DeviceState.CONNECTED

            await self._publish(device_id, samples[split:])
            await self._wait_for_count(device_id, len(samples))
            return MqttFailureObservation(
                disconnected=disconnected,
                reconnected=reconnected,
                gateway_degraded=gateway_degraded,
                gateway_recovered=gateway_recovered,
            )
        finally:
            await self._set_proxy_enabled(True)
            await consumer.stop()
            await gateway.stop()

    def _gateway(
        self, device_id: str, consumer: MqttTelemetryConsumer
    ) -> IndustrialProtocolGateway:
        registry = DeviceRegistry()
        registry.register(
            DeviceDefinition.model_validate(
                {
                    "device_id": device_id,
                    "protocol": "mqtt",
                    "state": {"operating_state": "RUNNING", "fault_state": "NORMAL"},
                    "mqtt": {"topic": f"industrial/devices/{device_id}/telemetry"},
                }
            )
        )
        return IndustrialProtocolGateway(
            registry=registry,
            sink=GatewayIngestionSink(
                self.sessions,
                self.redis,
                self.websocket_manager,
                self.counters,
                self.diagnosis,
            ),
            registration=DeviceRegistrationChecker(self.sessions),
            mqtt_connected=lambda: consumer.connected,
        )

    async def _prepare_proxy(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{self.control_url}/proxies/{self.proxy_name}")
            if response.status_code == 404:
                response = await client.post(
                    f"{self.control_url}/proxies",
                    json={
                        "name": self.proxy_name,
                        "listen": self.listen,
                        "upstream": self.upstream,
                        "enabled": True,
                    },
                )
                response.raise_for_status()
            else:
                response.raise_for_status()
                await self._set_proxy_enabled(True)

    async def _set_proxy_enabled(self, enabled: bool) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{self.control_url}/proxies/{self.proxy_name}",
                json={"enabled": enabled},
            )
            response.raise_for_status()

    async def _publish(self, device_id: str, samples: list[Telemetry]) -> None:
        if not samples:
            return
        topic = f"industrial/devices/{device_id}/telemetry"
        async with aiomqtt.Client(
            hostname=self.settings.mqtt_host,
            port=self.settings.mqtt_port,
            username=self.settings.mqtt_username,
            password=self.settings.mqtt_password,
        ) as client:
            for sample in samples:
                await client.publish(topic, sample.model_dump_json_mqtt().encode(), qos=1)

    async def _wait_for_count(self, device_id: str, expected: int) -> None:
        async def count_reached() -> bool:
            async with self.sessions() as session:
                count = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(TelemetryRow)
                        .where(TelemetryRow.device_id == device_id)
                    )
                    or 0
                )
            return count >= expected

        await self._wait_for_async(count_reached, f"MQTT ingestion did not reach {expected} rows")

    @staticmethod
    async def _wait_for(
        predicate: Callable[[], bool], message: str, timeout_seconds: float = 30.0
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.1)
        raise TimeoutError(message)

    @staticmethod
    async def _wait_for_async(
        predicate: Callable[[], Awaitable[bool]],
        message: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if await predicate():
                return
            await asyncio.sleep(0.1)
        raise TimeoutError(message)
