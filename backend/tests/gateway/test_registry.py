"""Gateway device registry behaviour."""

from __future__ import annotations

import pytest

from app.gateway.errors import GatewayConfigurationError
from app.gateway.registry import DeviceRegistry
from tests.gateway.conftest import modbus_definition, mqtt_definition


def test_register_then_look_up() -> None:
    registry = DeviceRegistry()
    definition = modbus_definition("MOTOR-001")
    registry.register(definition)
    assert registry.get("MOTOR-001") is definition
    assert registry.find("MOTOR-001") is definition
    assert "MOTOR-001" in registry
    assert len(registry) == 1


def test_find_returns_none_for_unknown_device() -> None:
    assert DeviceRegistry().find("NOPE") is None


def test_get_raises_for_unknown_device() -> None:
    with pytest.raises(GatewayConfigurationError) as excinfo:
        DeviceRegistry().get("NOPE")
    assert "not registered" in str(excinfo.value)


def test_duplicate_registration_is_rejected() -> None:
    registry = DeviceRegistry()
    registry.register(modbus_definition("MOTOR-001"))
    with pytest.raises(GatewayConfigurationError) as excinfo:
        registry.register(mqtt_definition("MOTOR-001"))
    assert "already registered" in str(excinfo.value)


def test_load_is_atomic_on_duplicate_ids() -> None:
    registry = DeviceRegistry()
    with pytest.raises(GatewayConfigurationError) as excinfo:
        registry.load([modbus_definition("A-1"), mqtt_definition("A-1"), modbus_definition("A-2")])
    assert "duplicate device ids: A-1" in str(excinfo.value)
    assert len(registry) == 0


def test_load_rejects_ids_already_present() -> None:
    registry = DeviceRegistry()
    registry.register(modbus_definition("A-1"))
    with pytest.raises(GatewayConfigurationError) as excinfo:
        registry.load([modbus_definition("A-2"), mqtt_definition("A-1")])
    assert "duplicate device ids: A-1" in str(excinfo.value)
    assert len(registry) == 1


def test_load_preserves_order_and_lists_all() -> None:
    registry = DeviceRegistry()
    registry.load([modbus_definition("A-1"), mqtt_definition("A-2"), modbus_definition("A-3")])
    assert [definition.device_id for definition in registry.list_definitions()] == [
        "A-1",
        "A-2",
        "A-3",
    ]


def test_enabled_filters_disabled_devices() -> None:
    registry = DeviceRegistry()
    registry.load(
        [
            modbus_definition("A-1", enabled=True),
            modbus_definition("A-2", enabled=False),
        ]
    )
    assert [definition.device_id for definition in registry.enabled()] == ["A-1"]
