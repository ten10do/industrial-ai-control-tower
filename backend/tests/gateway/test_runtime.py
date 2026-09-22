"""Device runtime lifecycle, retry, isolation, and graceful shutdown."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.gateway.ingestion import IngestionOutcome
from app.gateway.models import DeviceState
from app.gateway.runtime import DeviceRuntime, RetryPolicy
from tests.gateway.conftest import (
    FakeRegistration,
    FakeSink,
    ScriptedAdapter,
    modbus_definition,
    mqtt_definition,
    simulator_definition,
    wait_until,
)

FAST = RetryPolicy(
    failure_threshold=2,
    reconnect_threshold=3,
    max_reconnect_attempts=2,
    backoff_initial_seconds=0.001,
    backoff_max_seconds=0.01,
)

PATIENT = RetryPolicy(
    failure_threshold=2,
    reconnect_threshold=10_000,
    max_reconnect_attempts=2,
    backoff_initial_seconds=0.001,
    backoff_max_seconds=0.01,
)


def _use_adapter(monkeypatch: pytest.MonkeyPatch, adapter: ScriptedAdapter) -> None:
    monkeypatch.setattr("app.gateway.runtime.create_adapter", lambda *args, **kwargs: adapter)


def _runtime(
    definition: Any, sink: FakeSink, policy: RetryPolicy = FAST, **kwargs: Any
) -> DeviceRuntime:
    return DeviceRuntime(
        definition,
        sink=sink,
        registration=kwargs.pop("registration", FakeRegistration()),
        policy=policy,
        **kwargs,
    )


async def test_disabled_device_is_not_started() -> None:
    sink = FakeSink()
    runtime = _runtime(modbus_definition(enabled=False), sink)
    await runtime.start()
    assert runtime.status().state is DeviceState.DISABLED
    assert runtime.running is False
    await runtime.stop()


async def test_unregistered_device_fails_permanently() -> None:
    sink = FakeSink()
    registration = FakeRegistration({"MOTOR-001"})
    runtime = _runtime(modbus_definition("MOTOR-009"), sink, registration=registration)
    await runtime.start()
    await wait_until(lambda: runtime.status().state is DeviceState.ERROR)
    status = runtime.status()
    assert "not registered in the devices table" in (status.message or "")
    assert status.last_error is not None
    assert sink.published == []
    assert registration.queries == ["MOTOR-009"]


async def test_successful_polling_ingests_samples(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = ScriptedAdapter()
    _use_adapter(monkeypatch, adapter)
    sink = FakeSink()
    runtime = _runtime(modbus_definition(), sink)
    await runtime.start()
    await wait_until(lambda: len(sink.published) >= 2)
    status = runtime.status()
    assert status.state is DeviceState.CONNECTED
    assert status.samples_ingested >= 2
    assert status.samples_rejected == 0
    assert status.read_errors == 0
    assert status.last_success is not None
    assert status.message is None
    assert adapter.connect_calls == 1
    await runtime.stop()
    assert runtime.status().state is DeviceState.STOPPED
    assert adapter.disconnect_calls >= 1
    assert adapter.connected is False


async def test_stop_is_safe_before_start() -> None:
    runtime = _runtime(modbus_definition(), FakeSink())
    await runtime.stop()
    assert runtime.status().state is DeviceState.STOPPED


async def test_read_failures_degrade_the_device(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = ScriptedAdapter(read_errors=1000)
    _use_adapter(monkeypatch, adapter)
    sink = FakeSink()
    runtime = _runtime(modbus_definition(), sink, policy=PATIENT)
    await runtime.start()
    await wait_until(lambda: runtime.status().state is DeviceState.DEGRADED)
    status = runtime.status()
    assert status.consecutive_failures >= 2
    assert status.read_errors >= 2
    assert status.samples_ingested == 0
    assert "read failed" in (status.message or "")
    await runtime.stop()


async def test_repeated_failures_trigger_reconnection(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = ScriptedAdapter(read_errors=3)
    _use_adapter(monkeypatch, adapter)
    runtime = _runtime(modbus_definition(), FakeSink())
    await runtime.start()
    await wait_until(lambda: adapter.connect_calls >= 2)
    assert adapter.read_calls >= 3
    await runtime.stop()


async def test_reconnect_exhaustion_ends_in_error(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = ScriptedAdapter(connect_errors=100)
    _use_adapter(monkeypatch, adapter)
    runtime = _runtime(modbus_definition(), FakeSink())
    await runtime.start()
    await wait_until(lambda: runtime.status().state is DeviceState.ERROR)
    status = runtime.status()
    assert status.reconnect_attempts == FAST.max_reconnect_attempts
    assert adapter.connect_calls == FAST.max_reconnect_attempts + 1
    assert "recovery exhausted" in (status.message or "")
    assert runtime.running is False


async def test_ingestion_rejection_is_counted_and_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = ScriptedAdapter()
    _use_adapter(monkeypatch, adapter)
    sink = FakeSink(outcome=IngestionOutcome.REJECTED)
    runtime = _runtime(modbus_definition(), sink, policy=PATIENT)
    await runtime.start()
    await wait_until(lambda: runtime.status().samples_rejected >= 2)
    status = runtime.status()
    assert status.samples_ingested == 0
    assert status.state is DeviceState.DEGRADED
    assert "rejected by the ingestion contract" in (status.message or "")
    await runtime.stop()


async def test_ingestion_exception_is_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = ScriptedAdapter()
    _use_adapter(monkeypatch, adapter)
    sink = FakeSink()
    sink.error = RuntimeError("database is unreachable")
    runtime = _runtime(modbus_definition(), sink, policy=PATIENT)
    await runtime.start()
    await wait_until(lambda: runtime.status().state is DeviceState.DEGRADED)
    assert "ingestion failed" in (runtime.status().message or "")
    await runtime.stop()


async def test_backoff_schedule_is_bounded() -> None:
    policy = RetryPolicy(backoff_initial_seconds=1.0, backoff_max_seconds=10.0)
    assert [policy.delay_for(attempt) for attempt in range(6)] == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]
    assert policy.delay_for(-5) == 1.0


async def test_mqtt_device_is_passive(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the gateway must not build an adapter for a pushed protocol")

    monkeypatch.setattr("app.gateway.runtime.create_adapter", _forbidden)
    state = {"connected": False}
    runtime = _runtime(
        mqtt_definition(),
        FakeSink(),
        registration=FakeRegistration({"MQTT-001"}),
        mqtt_connected=lambda: bool(state["connected"]),
    )
    await runtime.start()
    assert runtime.running is False
    assert runtime.status().state is DeviceState.DEGRADED
    assert runtime.status().polled is False
    state["connected"] = True
    assert runtime.status().state is DeviceState.CONNECTED
    await runtime.stop()


async def test_simulator_without_a_source_fails_explicitly() -> None:
    runtime = _runtime(
        simulator_definition(), FakeSink(), registration=FakeRegistration({"SIM-001"})
    )
    await runtime.start()
    await wait_until(lambda: runtime.status().state is DeviceState.ERROR)
    assert "simulator sample source" in (runtime.status().message or "")


async def test_simulator_polls_through_the_real_adapter() -> None:
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "timestamp": datetime.now(UTC),
        "device_id": "SIM-001",
        "temperature_c": 61.2,
        "bearing_temperature_c": 64.1,
        "vibration_mm_s": 2.5,
        "current_a": 5.1,
        "voltage_v": 380.0,
        "rpm": 1440,
        "load_pct": 51.0,
        "power_kw": 2.95,
        "operating_state": "RUNNING",
        "fault_state": "NORMAL",
    }
    sink = FakeSink()
    runtime = _runtime(
        simulator_definition(),
        sink,
        registration=FakeRegistration({"SIM-001"}),
        simulator_source_factory=lambda device_id: lambda: payload,
    )
    await runtime.start()
    await wait_until(lambda: len(sink.published) >= 1)
    published = sink.published[0]
    assert published.device_id == "SIM-001"
    assert set(published.signals) == {
        "temperature",
        "bearing_temperature",
        "vibration",
        "current",
        "voltage",
        "rpm",
        "load",
        "power",
    }
    assert runtime.status().state is DeviceState.CONNECTED
    await runtime.stop()
