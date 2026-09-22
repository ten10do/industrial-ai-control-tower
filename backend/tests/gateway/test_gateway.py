"""Gateway orchestration: inventory, lifecycle, isolation, and summary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.gateway.errors import GatewayConfigurationError
from app.gateway.gateway import IndustrialProtocolGateway
from app.gateway.models import DeviceDefinition, DeviceState
from app.gateway.registry import DeviceRegistry
from app.gateway.runtime import RetryPolicy
from tests.gateway.conftest import (
    FakeRegistration,
    FakeSink,
    ScriptedAdapter,
    modbus_definition,
    wait_until,
)

FAST = RetryPolicy(
    failure_threshold=2,
    reconnect_threshold=3,
    max_reconnect_attempts=1,
    backoff_initial_seconds=0.001,
    backoff_max_seconds=0.01,
)

CONFIG = """
version: 1
devices:
  - device_id: MOTOR-001
    protocol: mqtt
    state:
      operating_state: RUNNING
      fault_state: NORMAL
    mqtt:
      topic: industrial/devices/MOTOR-001/telemetry
  - device_id: MOTOR-002
    protocol: mqtt
    enabled: false
    state:
      operating_state: RUNNING
      fault_state: NORMAL
    mqtt: {}
"""


def _gateway(
    definitions: list[DeviceDefinition],
    sink: FakeSink | None = None,
    registration: FakeRegistration | None = None,
    **kwargs: Any,
) -> IndustrialProtocolGateway:
    registry = DeviceRegistry()
    registry.load(definitions)
    return IndustrialProtocolGateway(
        registry=registry,
        sink=sink or FakeSink(),
        registration=registration or FakeRegistration(),
        policy=FAST,
        **kwargs,
    )


def test_from_config_file_builds_the_inventory(tmp_path: Path) -> None:
    path = tmp_path / "gateway_devices.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    gateway = IndustrialProtocolGateway.from_config_file(
        path,
        sink=FakeSink(),
        registration=FakeRegistration(),
        policy=FAST,
        mqtt_connected=lambda: True,
    )
    assert gateway.enabled is True
    assert gateway.config_file == "gateway_devices.yaml"
    assert gateway.loaded_at is not None
    assert [status.device_id for status in gateway.statuses()] == ["MOTOR-001", "MOTOR-002"]


def test_from_config_file_propagates_configuration_errors(tmp_path: Path) -> None:
    with pytest.raises(GatewayConfigurationError):
        IndustrialProtocolGateway.from_config_file(
            tmp_path / "absent.yaml", sink=FakeSink(), registration=FakeRegistration()
        )


async def test_start_and_stop_all_devices() -> None:
    gateway = _gateway(
        [modbus_definition("MOTOR-001")],
        registration=FakeRegistration({"MOTOR-001"}),
    )
    await gateway.start()
    await gateway.stop()
    assert gateway.status("MOTOR-001").state is DeviceState.STOPPED


async def test_failure_is_isolated_between_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    healthy = ScriptedAdapter()
    broken = ScriptedAdapter(connect_errors=1000)
    adapters = {"MOTOR-001": healthy, "MOTOR-002": broken}
    monkeypatch.setattr(
        "app.gateway.runtime.create_adapter", lambda *args, **kwargs: adapters[kwargs["device_id"]]
    )
    sink = FakeSink()
    gateway = _gateway(
        [modbus_definition("MOTOR-001"), modbus_definition("MOTOR-002")],
        sink,
        FakeRegistration({"MOTOR-001", "MOTOR-002"}),
    )
    await gateway.start()
    await wait_until(lambda: len(sink.published) >= 1)
    await wait_until(lambda: gateway.status("MOTOR-002").state is DeviceState.ERROR)
    assert gateway.status("MOTOR-001").state is DeviceState.CONNECTED
    summary = gateway.summary()
    assert summary.states["CONNECTED"] == 1
    assert summary.states["ERROR"] == 1
    assert summary.total_samples_ingested >= 1
    await gateway.stop()
    assert gateway.status("MOTOR-002").state is DeviceState.STOPPED


async def test_start_and_stop_a_single_device(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = ScriptedAdapter()
    monkeypatch.setattr("app.gateway.runtime.create_adapter", lambda *args, **kwargs: adapter)
    gateway = _gateway(
        [modbus_definition("MOTOR-001")], registration=FakeRegistration({"MOTOR-001"})
    )
    await gateway.start_device("MOTOR-001")
    assert gateway.status("MOTOR-001").state in {
        DeviceState.STARTING,
        DeviceState.CONNECTING,
        DeviceState.CONNECTED,
    }
    stopped = await gateway.stop_device("MOTOR-001")
    assert stopped.state is DeviceState.STOPPED


def test_unknown_device_is_rejected_on_status() -> None:
    gateway = _gateway([modbus_definition("MOTOR-001")])
    with pytest.raises(GatewayConfigurationError):
        gateway.status("NOPE")


async def test_unknown_device_is_rejected_on_lifecycle_calls() -> None:
    gateway = _gateway([modbus_definition("MOTOR-001")])
    with pytest.raises(GatewayConfigurationError):
        await gateway.start_device("NOPE")
    with pytest.raises(GatewayConfigurationError):
        await gateway.stop_device("NOPE")


def test_register_adds_a_device() -> None:
    gateway = _gateway([modbus_definition("MOTOR-001")])
    status = gateway.register(modbus_definition("MOTOR-002"))
    assert status.device_id == "MOTOR-002"
    assert [item.device_id for item in gateway.statuses()] == ["MOTOR-001", "MOTOR-002"]


def test_register_rejects_duplicates() -> None:
    gateway = _gateway([modbus_definition("MOTOR-001")])
    with pytest.raises(GatewayConfigurationError):
        gateway.register(modbus_definition("MOTOR-001"))


def test_summary_counts_all_states_and_disabled_devices() -> None:
    gateway = _gateway(
        [modbus_definition("MOTOR-001"), modbus_definition("MOTOR-002", enabled=False)]
    )
    summary = gateway.summary()
    assert summary.device_count == 2
    assert summary.enabled_device_count == 1
    assert set(summary.states) == {state.value for state in DeviceState}
    assert summary.states["DISABLED"] == 1
    assert summary.total_samples_ingested == 0
    assert summary.gateway_available is True
