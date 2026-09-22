"""End-to-end tests for the read-only OPC UA adapter."""

import socket
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from asyncua import ua
from asyncua.client.client import Client

from adapters import create_adapter
from adapters.exceptions import AdapterConnectionError
from adapters.models import AdapterStatus, ProtocolType, SignalQuality, UnifiedTelemetry
from adapters.opcua_adapter import OpcUaAdapter

SIMULATOR_ROOT = Path(__file__).resolve().parents[3] / "simulator"
sys.path.insert(0, str(SIMULATOR_ROOT))
from simulator.opcua import (  # type: ignore[import-not-found]  # noqa: E402
    DETERMINISTIC_VALUES,
    OpcUaServerSimulator,
)


def _unused_endpoint() -> str:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    return f"opc.tcp://127.0.0.1:{port}/industrial-ai/"


@pytest.fixture
async def opcua_server() -> AsyncIterator[OpcUaServerSimulator]:
    server = OpcUaServerSimulator(endpoint=_unused_endpoint())
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_server_exposes_read_only_deterministic_node(
    opcua_server: OpcUaServerSimulator,
) -> None:
    async with Client(opcua_server.endpoint) as client:
        temperature = client.get_node(opcua_server.node_ids["temperature"])

        assert await temperature.read_value() == DETERMINISTIC_VALUES["temperature"]
        access = await temperature.get_user_access_level()
        assert ua.AccessLevel.CurrentRead in access
        assert ua.AccessLevel.CurrentWrite not in access


@pytest.mark.asyncio
async def test_adapter_connects_reads_and_reports_health(
    opcua_server: OpcUaServerSimulator,
) -> None:
    adapter = OpcUaAdapter(
        endpoint=opcua_server.endpoint,
        device_id="MOTOR-001",
        nodes={signal: {"node_id": node_id} for signal, node_id in opcua_server.node_ids.items()},
    )

    await adapter.connect()
    assert adapter.health().status is AdapterStatus.CONNECTED
    assert adapter.health().endpoint == opcua_server.endpoint

    telemetry = await adapter.read()

    assert UnifiedTelemetry.model_validate(telemetry.model_dump()) == telemetry
    assert telemetry.device_id == "MOTOR-001"
    assert telemetry.source_protocol is ProtocolType.OPC_UA
    assert telemetry.quality is SignalQuality.GOOD
    assert telemetry.signals == {
        signal: float(value) for signal, value in DETERMINISTIC_VALUES.items()
    }
    assert telemetry.metadata["node_ids"] == opcua_server.node_ids
    assert adapter.health().last_success is not None

    await adapter.disconnect()
    assert adapter.health().status is AdapterStatus.DISCONNECTED


def test_shared_registry_creates_opcua_adapter() -> None:
    adapter = create_adapter(
        "opc_ua",
        endpoint="opc.tcp://127.0.0.1:4840/industrial-ai/",
        device_id="MOTOR-001",
        nodes={"temperature": "ns=2;s=MOTOR-001/Temperature"},
    )

    assert isinstance(adapter, OpcUaAdapter)
    assert adapter.protocol is ProtocolType.OPC_UA


@pytest.mark.asyncio
async def test_connection_failure_uses_typed_error_and_error_health() -> None:
    endpoint = _unused_endpoint()
    adapter = OpcUaAdapter(
        endpoint=endpoint,
        device_id="MOTOR-001",
        nodes={"temperature": "ns=2;s=MOTOR-001/Temperature"},
        timeout_seconds=0.2,
    )

    with pytest.raises(AdapterConnectionError):
        await adapter.connect()

    health = adapter.health()
    assert health.status is AdapterStatus.ERROR
    assert health.last_error is not None
    assert health.endpoint == endpoint
    assert health.message == "OPC UA connection failed."
