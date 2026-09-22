"""End-to-end tests for the read-only Modbus TCP adapter."""

import inspect
import socket
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pymodbus.client import AsyncModbusTcpClient

from adapters import create_adapter
from adapters.exceptions import AdapterConnectionError
from adapters.modbus_adapter import ModbusTcpAdapter
from adapters.models import AdapterStatus, ProtocolType, SignalQuality, UnifiedTelemetry

SIMULATOR_ROOT = Path(__file__).resolve().parents[3] / "simulator"
sys.path.insert(0, str(SIMULATOR_ROOT))
from simulator.modbus import (  # type: ignore[import-not-found]  # noqa: E402
    REGISTER_VALUES,
    ModbusTcpServerSimulator,
)

REGISTER_MAPPING: dict[str, dict[str, object]] = {
    "temperature": {"address": 40001, "scale": 0.1, "unit": "celsius"},
    "current": {"address": 40002, "scale": 0.01, "unit": "ampere"},
    "vibration": {"address": 40003, "scale": 0.01, "unit": "mm_s"},
    "rpm": {"address": 40004, "scale": 1, "unit": "rpm"},
    "load": {"address": 40005, "scale": 0.1, "unit": "percent"},
}


def _unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture
async def modbus_server() -> AsyncIterator[ModbusTcpServerSimulator]:
    server = ModbusTcpServerSimulator(port=_unused_port())
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_server_exposes_deterministic_holding_register(
    modbus_server: ModbusTcpServerSimulator,
) -> None:
    client = AsyncModbusTcpClient(modbus_server.host, port=modbus_server.port)
    assert await client.connect()
    try:
        response = await client.read_holding_registers(0, count=1, device_id=1)
        assert not response.isError()
        assert response.registers == [REGISTER_VALUES[40001]]
    finally:
        client.close()


@pytest.mark.asyncio
async def test_register_mapping_becomes_unified_telemetry(
    modbus_server: ModbusTcpServerSimulator,
) -> None:
    adapter = ModbusTcpAdapter(
        host=modbus_server.host,
        port=modbus_server.port,
        device_id="MOTOR-001",
        registers=REGISTER_MAPPING,
    )

    await adapter.connect()
    assert adapter.health().status is AdapterStatus.CONNECTED
    assert adapter.health().host == modbus_server.host
    assert adapter.health().port == modbus_server.port

    telemetry = await adapter.read()

    assert UnifiedTelemetry.model_validate(telemetry.model_dump()) == telemetry
    assert telemetry.device_id == "MOTOR-001"
    assert telemetry.source_protocol is ProtocolType.MODBUS_TCP
    assert telemetry.quality is SignalQuality.GOOD
    assert telemetry.signals == pytest.approx(
        {
            "temperature": 68.5,
            "current": 12.4,
            "vibration": 7.1,
            "rpm": 1480.0,
            "load": 72.0,
        }
    )
    assert telemetry.metadata["registers"]["temperature"]["address"] == 40001
    assert adapter.health().last_success is not None

    await adapter.disconnect()
    assert adapter.health().status is AdapterStatus.DISCONNECTED


def test_shared_registry_creates_modbus_adapter() -> None:
    adapter = create_adapter(
        "modbus_tcp",
        host="127.0.0.1",
        port=5020,
        device_id="MOTOR-001",
        registers=REGISTER_MAPPING,
    )

    assert isinstance(adapter, ModbusTcpAdapter)
    assert adapter.protocol is ProtocolType.MODBUS_TCP


@pytest.mark.asyncio
async def test_connection_failure_uses_typed_error_and_error_health() -> None:
    port = _unused_port()
    server = ModbusTcpServerSimulator(port=port)
    await server.start()
    await server.stop()
    adapter = ModbusTcpAdapter(
        host="127.0.0.1",
        port=port,
        device_id="MOTOR-001",
        registers=REGISTER_MAPPING,
        timeout_seconds=0.2,
    )

    with pytest.raises(AdapterConnectionError):
        await adapter.connect()

    health = adapter.health()
    assert health.status is AdapterStatus.ERROR
    assert health.last_error is not None
    assert health.host == "127.0.0.1"
    assert health.port == port
    assert health.message == "Modbus TCP connection failed."


def test_adapter_and_server_expose_no_control_operations() -> None:
    source = inspect.getsource(ModbusTcpAdapter) + inspect.getsource(ModbusTcpServerSimulator)

    for target in ("register", "registers", "coil"):
        assert f"write_{target}" not in source
