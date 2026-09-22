"""Shared fakes for gateway tests.

The gateway is tested without a database. ``FakeSink`` and ``FakeRegistration`` stand
in for the ingestion boundary and the device registration lookup, and
``ScriptedAdapter`` replaces the adapter the runtime would otherwise build through the
protocol registry. The canonical payload is separately proven compatible with the real
ingestion contract in ``test_normalizer.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from adapters.base import IndustrialProtocolAdapter
from adapters.exceptions import AdapterConnectionError, AdapterReadError
from adapters.models import (
    AdapterHealth,
    AdapterStatus,
    ProtocolType,
    SignalQuality,
    UnifiedTelemetry,
)
from app.gateway.ingestion import IngestionOutcome
from app.gateway.models import CANONICAL_SIGNAL_FIELDS, DeviceDefinition, DeviceStateDefinition

BASE_SIGNALS: dict[str, float] = {
    "temperature": 61.2,
    "bearing_temperature": 64.1,
    "vibration": 2.5,
    "current": 5.1,
    "voltage": 380.0,
    "rpm": 1440.0,
    "load": 51.0,
    "power": 2.95,
}


def sample(device_id: str = "MOTOR-001", **overrides: float) -> UnifiedTelemetry:
    """Return a complete canonical sample."""

    return UnifiedTelemetry(
        device_id=device_id,
        timestamp=datetime.now(UTC),
        signals={**BASE_SIGNALS, **overrides},
        source_protocol=ProtocolType.MODBUS_TCP,
        quality=SignalQuality.GOOD,
    )


def state_definition(**overrides: Any) -> DeviceStateDefinition:
    payload: dict[str, Any] = {"operating_state": "RUNNING", "fault_state": "NORMAL"}
    payload.update(overrides)
    return DeviceStateDefinition.model_validate(payload)


def _definition(
    device_id: str, payload: dict[str, Any], overrides: dict[str, Any]
) -> DeviceDefinition:
    merged: dict[str, Any] = {
        "device_id": device_id,
        "enabled": True,
        "poll_interval_ms": 100,
        "state": {"operating_state": "RUNNING", "fault_state": "NORMAL"},
        **payload,
    }
    merged.update(overrides)
    return DeviceDefinition.model_validate(merged)


def modbus_definition(device_id: str = "MOTOR-001", **overrides: Any) -> DeviceDefinition:
    """Return a fully covered Modbus TCP definition."""

    registers = {
        signal: {"address": 40001 + index, "scale": 1.0, "unit": None}
        for index, signal in enumerate(CANONICAL_SIGNAL_FIELDS)
    }
    return _definition(
        device_id,
        {
            "protocol": "modbus_tcp",
            "modbus_tcp": {"host": "localhost", "port": 5020, "registers": registers},
        },
        overrides,
    )


def opcua_definition(device_id: str = "MOTOR-002", **overrides: Any) -> DeviceDefinition:
    """Return a fully covered OPC UA definition."""

    nodes = {signal: {"node_id": f"ns=2;s={signal}"} for signal in CANONICAL_SIGNAL_FIELDS}
    return _definition(
        device_id,
        {
            "protocol": "opc_ua",
            "opc_ua": {"endpoint": "opc.tcp://localhost:4840/test/", "nodes": nodes},
        },
        overrides,
    )


def simulator_definition(device_id: str = "SIM-001", **overrides: Any) -> DeviceDefinition:
    """Return a simulator definition with no parameters."""

    return _definition(device_id, {"protocol": "simulator", "simulator": {}}, overrides)


def mqtt_definition(device_id: str = "MQTT-001", **overrides: Any) -> DeviceDefinition:
    """Return a passive MQTT inventory entry."""

    return _definition(
        device_id,
        {"protocol": "mqtt", "mqtt": {"topic": f"industrial/devices/{device_id}/telemetry"}},
        overrides,
    )


class FakeSink:
    """``TelemetrySink`` test double."""

    def __init__(self, outcome: IngestionOutcome = IngestionOutcome.PERSISTED) -> None:
        self.outcome = outcome
        self.published: list[UnifiedTelemetry] = []
        self.definitions: list[DeviceStateDefinition] = []
        self.error: Exception | None = None

    async def publish(
        self, telemetry: UnifiedTelemetry, definition: DeviceStateDefinition
    ) -> IngestionOutcome:
        if self.error is not None:
            raise self.error
        self.published.append(telemetry)
        self.definitions.append(definition)
        return self.outcome


class FakeRegistration:
    """``RegistrationChecker`` test double."""

    def __init__(self, known: set[str] | None = None) -> None:
        self.known = {"MOTOR-001"} if known is None else known
        self.queries: list[str] = []

    async def exists(self, device_id: str) -> bool:
        self.queries.append(device_id)
        return device_id in self.known


class ScriptedAdapter(IndustrialProtocolAdapter):
    """Adapter whose connect and read outcomes are scripted by the test."""

    def __init__(
        self,
        *,
        connect_errors: int = 0,
        read_errors: int = 0,
        telemetry_factory: Callable[[], UnifiedTelemetry] | None = None,
    ) -> None:
        self.connect_errors = connect_errors
        self.read_errors = read_errors
        self.telemetry_factory = telemetry_factory or (lambda: sample())
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.read_calls = 0
        self.connected = False

    @property
    def protocol(self) -> ProtocolType:
        return ProtocolType.MODBUS_TCP

    async def connect(self) -> None:
        self.connect_calls += 1
        if self.connect_errors > 0:
            self.connect_errors -= 1
            raise AdapterConnectionError("scripted connect failure")
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    async def read(self) -> UnifiedTelemetry:
        self.read_calls += 1
        if self.read_errors > 0:
            self.read_errors -= 1
            raise AdapterReadError("scripted read failure")
        return self.telemetry_factory()

    def health(self) -> AdapterHealth:
        return AdapterHealth(
            protocol=self.protocol,
            status=AdapterStatus.CONNECTED if self.connected else AdapterStatus.DISCONNECTED,
        )


async def wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    """Wait for a predicate, failing the test rather than hanging."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition was not met before the timeout")
        await asyncio.sleep(0.01)
