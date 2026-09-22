"""Read-only OPC UA adapter backed by asyncua."""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from asyncua.client.client import Client
from pydantic import ValidationError

from adapters.base import IndustrialProtocolAdapter
from adapters.exceptions import (
    AdapterConfigurationError,
    AdapterConnectionError,
    AdapterReadError,
)
from adapters.models import (
    AdapterHealth,
    AdapterStatus,
    ProtocolType,
    SignalQuality,
    UnifiedTelemetry,
)

NodeDefinition = str | Mapping[str, str]


class OpcUaAdapter(IndustrialProtocolAdapter):
    """Read configured OPC UA nodes without exposing write or control operations."""

    def __init__(
        self,
        endpoint: str,
        device_id: str,
        nodes: Mapping[str, NodeDefinition],
        timeout_seconds: float = 4.0,
    ) -> None:
        if not endpoint.startswith("opc.tcp://"):
            raise AdapterConfigurationError("OPC UA endpoint must use opc.tcp://.")
        if not device_id.strip():
            raise AdapterConfigurationError("OPC UA device_id must not be blank.")
        if timeout_seconds <= 0:
            raise AdapterConfigurationError("OPC UA timeout_seconds must be positive.")
        self._node_ids = self._normalize_nodes(nodes)
        self.endpoint = endpoint
        self.device_id = device_id
        self.timeout_seconds = timeout_seconds
        self._client: Client | None = None
        self._status = AdapterStatus.DISCONNECTED
        self._last_success: datetime | None = None
        self._last_error: datetime | None = None
        self._message: str | None = None

    @staticmethod
    def _normalize_nodes(nodes: Mapping[str, NodeDefinition]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for signal, definition in nodes.items():
            node_id = definition if isinstance(definition, str) else definition.get("node_id", "")
            if not signal.strip() or not node_id.strip():
                raise AdapterConfigurationError(
                    "OPC UA node mapping requires non-blank signal names and node_id values."
                )
            normalized[signal] = node_id
        if not normalized:
            raise AdapterConfigurationError("OPC UA node mapping must not be empty.")
        return normalized

    @property
    def protocol(self) -> ProtocolType:
        return ProtocolType.OPC_UA

    async def connect(self) -> None:
        if self._status is AdapterStatus.CONNECTED:
            return
        client = Client(url=self.endpoint, timeout=self.timeout_seconds)
        try:
            await client.connect()
        except Exception as exc:
            self._record_error("OPC UA connection failed.")
            raise AdapterConnectionError(self._message) from exc
        self._client = client
        self._status = AdapterStatus.CONNECTED
        self._message = None

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except Exception as exc:
                self._record_error("OPC UA disconnect failed.")
                raise AdapterConnectionError(self._message) from exc
        self._status = AdapterStatus.DISCONNECTED
        self._message = None

    async def read(self) -> UnifiedTelemetry:
        if self._client is None or self._status is not AdapterStatus.CONNECTED:
            raise AdapterConnectionError("OPC UA adapter is not connected.")
        try:
            values = await asyncio.gather(
                *(
                    self._client.get_node(node_id).read_value()
                    for node_id in self._node_ids.values()
                )
            )
            signals = {
                signal: self._numeric_value(signal, value)
                for signal, value in zip(self._node_ids, values, strict=True)
            }
            telemetry = UnifiedTelemetry(
                device_id=self.device_id,
                timestamp=datetime.now(UTC),
                signals=signals,
                source_protocol=self.protocol,
                quality=SignalQuality.GOOD,
                metadata={"endpoint": self.endpoint, "node_ids": dict(self._node_ids)},
            )
        except (AdapterReadError, ValidationError) as exc:
            self._record_error("OPC UA values could not be normalized.")
            raise AdapterReadError(self._message) from exc
        except Exception as exc:
            self._record_error("OPC UA node read failed.")
            raise AdapterReadError(self._message) from exc
        self._status = AdapterStatus.CONNECTED
        self._last_success = datetime.now(UTC)
        self._message = None
        return telemetry

    @staticmethod
    def _numeric_value(signal: str, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise AdapterReadError(f"OPC UA signal {signal} is not numeric.")
        return float(value)

    def _record_error(self, message: str) -> None:
        self._status = AdapterStatus.ERROR
        self._last_error = datetime.now(UTC)
        self._message = message

    def health(self) -> AdapterHealth:
        return AdapterHealth(
            protocol=self.protocol,
            status=self._status,
            last_success=self._last_success,
            last_error=self._last_error,
            message=self._message,
            endpoint=self.endpoint,
        )
