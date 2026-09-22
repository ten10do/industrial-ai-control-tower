"""Connectivity API surface.

These tests drive the real application routes and a real gateway object. The
database-facing collaborators are replaced by fakes, so no database is required.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.gateway.gateway import IndustrialProtocolGateway
from app.gateway.models import DeviceState
from app.gateway.registry import DeviceRegistry
from app.gateway.runtime import RetryPolicy
from app.main import app
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

V1 = "/api/v1/connectivity"
LEGACY = "/api/connectivity"


def _gateway(sink: FakeSink, registration: FakeRegistration) -> IndustrialProtocolGateway:
    registry = DeviceRegistry()
    registry.load([modbus_definition("MOTOR-001")])
    return IndustrialProtocolGateway(
        registry=registry,
        sink=sink,
        registration=registration,
        enabled=True,
        config_file="gateway_devices.yaml",
        policy=FAST,
    )


def _configure(
    gateway: IndustrialProtocolGateway | None, *, enabled: bool = True, error: str | None = None
) -> TestClient:
    app.state.gateway = gateway
    app.state.gateway_enabled = enabled
    app.state.gateway_error = error
    return TestClient(app)


def test_summary_reports_a_disabled_gateway() -> None:
    client = _configure(None, enabled=False)
    response = client.get(f"{V1}/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["gateway_enabled"] is False
    assert body["gateway_available"] is False
    assert body["device_count"] == 0


def test_summary_surfaces_a_configuration_error() -> None:
    client = _configure(None, enabled=True, error="gateway configuration is empty")
    body = client.get(f"{V1}/summary").json()
    assert body["gateway_enabled"] is True
    assert body["gateway_available"] is False
    assert body["gateway_error"] == "gateway configuration is empty"


def test_devices_are_empty_when_disabled() -> None:
    client = _configure(None, enabled=False)
    response = client.get(f"{V1}/devices")
    assert response.status_code == 200
    assert response.json() == []


def test_device_detail_is_unavailable_when_disabled() -> None:
    client = _configure(None, enabled=False)
    response = client.get(f"{V1}/devices/MOTOR-001")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CONNECTIVITY_DISABLED"


def test_summary_reports_the_inventory() -> None:
    client = _configure(_gateway(FakeSink(), FakeRegistration()))
    body = client.get(f"{V1}/summary").json()
    assert body["gateway_available"] is True
    assert body["config_file"] == "gateway_devices.yaml"
    assert body["device_count"] == 1
    assert body["states"]["STOPPED"] == 1


def test_device_list_and_detail() -> None:
    client = _configure(_gateway(FakeSink(), FakeRegistration()))
    listed = client.get(f"{V1}/devices").json()
    assert len(listed) == 1
    assert listed[0]["device_id"] == "MOTOR-001"
    assert listed[0]["protocol"] == "modbus_tcp"
    detail = client.get(f"{V1}/devices/MOTOR-001").json()
    assert detail["polled"] is True
    assert detail["state_mode"] == "static"


def test_unknown_device_returns_not_found() -> None:
    client = _configure(_gateway(FakeSink(), FakeRegistration()))
    response = client.get(f"{V1}/devices/MOTOR-404")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONNECTIVITY_DEVICE_NOT_FOUND"


async def test_start_and_stop_a_device(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = ScriptedAdapter()
    monkeypatch.setattr("app.gateway.runtime.create_adapter", lambda *args, **kwargs: adapter)
    sink = FakeSink()
    client = _configure(_gateway(sink, FakeRegistration({"MOTOR-001"})))
    started = client.post(f"{V1}/devices/MOTOR-001/start")
    assert started.status_code == 200
    assert started.json()["state"] in {"STARTING", "CONNECTING", "CONNECTED"}
    await wait_until(lambda: len(sink.published) >= 1)
    stopped = client.post(f"{V1}/devices/MOTOR-001/stop")
    assert stopped.status_code == 200
    assert stopped.json()["state"] == DeviceState.STOPPED.value


def test_start_unknown_device_returns_not_found() -> None:
    client = _configure(_gateway(FakeSink(), FakeRegistration()))
    response = client.post(f"{V1}/devices/MOTOR-404/start")
    assert response.status_code == 404


def test_both_prefixes_serve_the_same_surface() -> None:
    client = _configure(_gateway(FakeSink(), FakeRegistration()))
    for prefix in (V1, LEGACY):
        assert client.get(f"{prefix}/summary").status_code == 200
        assert client.get(f"{prefix}/devices").status_code == 200
