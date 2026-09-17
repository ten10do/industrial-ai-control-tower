"""MQTT publisher implementation using Eclipse Paho."""

from __future__ import annotations

import json
import logging
from typing import Any

import paho.mqtt.client as mqtt

from simulator.models import Telemetry
from simulator.publishers.base import TelemetryPublisher

logger = logging.getLogger(__name__)


class MqttPublisher(TelemetryPublisher):
    """Publishes telemetry to an MQTT broker."""

    def __init__(
        self,
        broker_host: str,
        broker_port: int = 1883,
        topic_prefix: str = "industrial",
        client_id: str | None = None,
    ) -> None:
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.topic_prefix = topic_prefix
        self._client_id = client_id
        self._client: mqtt.Client | None = None
        self._connected = False

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: dict[str, Any],
        rc: int,
        properties: Any = None,
    ) -> None:
        if rc == 0:
            self._connected = True
            logger.info("mqtt_connected", extra={"broker": self.broker_host})
        else:
            self._connected = False
            logger.error("mqtt_connect_failed", extra={"broker": self.broker_host, "rc": rc})

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: Any,
        rc: int,
        properties: Any = None,
    ) -> None:
        self._connected = False
        logger.warning("mqtt_disconnected", extra={"broker": self.broker_host, "rc": rc})

    def connect(self) -> None:
        if self._client is not None:
            return

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,  # type: ignore[attr-defined]
            client_id=self._client_id,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect  # type: ignore[assignment]

        try:
            self._client.connect(self.broker_host, self.broker_port)
            self._client.loop_start()
        except Exception as exc:
            logger.error(
                "mqtt_connection_error",
                extra={"broker": self.broker_host, "error": str(exc)},
            )
            raise

    def disconnect(self) -> None:
        if self._client is None:
            return
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception as exc:
            logger.error("mqtt_disconnect_error", extra={"error": str(exc)})
            raise
        finally:
            self._client = None
            self._connected = False

    def publish(self, telemetry: Telemetry) -> None:
        if self._client is None:
            raise RuntimeError("MQTT publisher is not connected")

        topic = f"{self.topic_prefix}/devices/{telemetry.device_id}/telemetry"
        payload = telemetry.model_dump_json()
        result = self._client.publish(topic, payload, qos=1)

        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.error(
                "mqtt_publish_failed",
                extra={"topic": topic, "rc": result.rc},
            )
            raise RuntimeError(f"MQTT publish failed with rc={result.rc}")

        logger.debug("mqtt_published", extra={"topic": topic})

    def publish_status(self, device_id: str, status: str) -> None:
        """Publish a device status message (online / offline)."""
        if self._client is None:
            raise RuntimeError("MQTT publisher is not connected")

        topic = f"{self.topic_prefix}/devices/{device_id}/status"
        payload = json.dumps({"device_id": device_id, "status": status})
        self._client.publish(topic, payload, qos=1, retain=True)
