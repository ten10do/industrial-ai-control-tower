"""Simulator-to-unified-telemetry adapter tests."""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from adapters.exceptions import AdapterConnectionError, AdapterReadError
from adapters.models import AdapterStatus, ProtocolType, SignalQuality
from adapters.simulator_adapter import SimulatorAdapter

SIMULATOR_ROOT = Path(__file__).resolve().parents[3] / "simulator"
sys.path.insert(0, str(SIMULATOR_ROOT))
from simulator.models import IndustrialMotor  # type: ignore[import-not-found]  # noqa: E402


@pytest.mark.asyncio
async def test_existing_simulator_output_becomes_unified_telemetry() -> None:
    sample = IndustrialMotor(device_id="MOTOR-001", seed=42).step(
        timestamp=datetime(2026, 9, 22, 10, tzinfo=UTC)
    )
    adapter = SimulatorAdapter(source=sample.model_dump)

    await adapter.connect()
    telemetry = await adapter.read()

    assert telemetry.device_id == sample.device_id
    assert telemetry.source_protocol is ProtocolType.SIMULATOR
    assert telemetry.quality is SignalQuality.GOOD
    assert telemetry.signals == {
        "temperature": sample.temperature_c,
        "bearing_temperature": sample.bearing_temperature_c,
        "vibration": sample.vibration_mm_s,
        "current": sample.current_a,
        "voltage": sample.voltage_v,
        "rpm": float(sample.rpm),
        "load": sample.load_pct,
        "power": sample.power_kw,
    }
    assert telemetry.metadata["operating_state"] == sample.operating_state
    assert adapter.health().status is AdapterStatus.CONNECTED
    assert adapter.health().last_success is not None

    await adapter.disconnect()
    assert adapter.health().status is AdapterStatus.DISCONNECTED


@pytest.mark.asyncio
async def test_read_while_disconnected_raises_connection_error() -> None:
    adapter = SimulatorAdapter(source=dict)

    with pytest.raises(AdapterConnectionError):
        await adapter.read()


@pytest.mark.asyncio
async def test_invalid_simulator_payload_raises_read_error_and_updates_health() -> None:
    adapter = SimulatorAdapter(source=lambda: {"device_id": "MOTOR-001"})
    await adapter.connect()

    with pytest.raises(AdapterReadError):
        await adapter.read()

    health = adapter.health()
    assert health.status is AdapterStatus.ERROR
    assert health.last_error is not None
    assert health.message == "Simulator payload could not be normalized."
