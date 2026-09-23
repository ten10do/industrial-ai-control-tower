"""Reconnectable async MQTT telemetry consumer."""

import asyncio
import logging

import aiomqtt
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.platform_observability.metrics import mqtt_reconnect_total
from app.platform_observability.tasks import monitor_background_task
from app.services.diagnosis import OnlineDiagnosisCoordinator
from app.services.telemetry import IngestionCounters, TelemetryService
from app.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


class MqttTelemetryConsumer:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        redis: Redis,
        websocket_manager: WebSocketManager,
        counters: IngestionCounters,
        diagnosis: OnlineDiagnosisCoordinator | None = None,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.redis = redis
        self.websocket_manager = websocket_manager
        self.counters = counters
        self.diagnosis = diagnosis
        self._task: asyncio.Task[None] | None = None
        self.connected = False

    def start(self) -> None:
        if self._task is None:
            self._task = monitor_background_task(
                asyncio.create_task(self._run(), name="mqtt-telemetry-consumer"),
                name="mqtt-telemetry-consumer",
            )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            self.connected = False

    async def _run(self) -> None:
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=self.settings.mqtt_host,
                    port=self.settings.mqtt_port,
                    username=self.settings.mqtt_username,
                    password=self.settings.mqtt_password,
                ) as client:
                    await client.subscribe(self.settings.mqtt_topic, qos=1)
                    self.connected = True
                    logger.info("mqtt_connected", extra={"topic": self.settings.mqtt_topic})
                    async for message in client.messages:
                        async with self.sessions() as session:
                            service = TelemetryService(
                                session,
                                self.redis,
                                self.websocket_manager,
                                self.counters,
                                self.diagnosis,
                            )
                            try:
                                payload = message.payload
                                if isinstance(payload, str):
                                    body = payload.encode()
                                elif isinstance(payload, int | float):
                                    body = str(payload).encode()
                                elif payload is None:
                                    body = b""
                                else:
                                    body = bytes(payload)
                                await service.ingest_payload(str(message.topic), body)
                            except Exception:
                                await session.rollback()
                                logger.exception(
                                    "mqtt_message_processing_failed",
                                    extra={"topic": str(message.topic)},
                                )
            except asyncio.CancelledError:
                raise
            except Exception:
                self.connected = False
                mqtt_reconnect_total.inc()
                logger.exception("mqtt_connection_failed")
                await asyncio.sleep(2)
            finally:
                self.connected = False
