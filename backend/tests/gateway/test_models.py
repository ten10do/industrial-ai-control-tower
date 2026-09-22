"""Gateway device definition validation."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.gateway.models import CANONICAL_SIGNAL_FIELDS, DeviceDefinition, StateRule


def _registers(omit: set[str] | None = None, extra: set[str] | None = None) -> dict[str, Any]:
    mapping: dict[str, Any] = {
        signal: {"address": 40001 + index, "scale": 1.0}
        for index, signal in enumerate(CANONICAL_SIGNAL_FIELDS)
        if signal not in (omit or set())
    }
    for index, name in enumerate(sorted(extra or set())):
        mapping[name] = {"address": 41000 + index, "scale": 1.0}
    return mapping


def _modbus_payload(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        "device_id": "MOTOR-001",
        "protocol": "modbus_tcp",
        "state": {"operating_state": "RUNNING", "fault_state": "NORMAL"},
        "modbus_tcp": {"host": "localhost", "port": 5020, "registers": mapping},
    }


def test_full_canonical_coverage_is_accepted() -> None:
    definition = DeviceDefinition.model_validate(_modbus_payload(_registers()))
    assert definition.modbus_tcp is not None
    assert set(definition.modbus_tcp.registers) == set(CANONICAL_SIGNAL_FIELDS)


def test_missing_signal_is_rejected_and_named() -> None:
    with pytest.raises(ValidationError) as excinfo:
        DeviceDefinition.model_validate(_modbus_payload(_registers(omit={"voltage"})))
    assert "missing canonical signals: voltage" in str(excinfo.value)


def test_unknown_signal_is_rejected_and_named() -> None:
    with pytest.raises(ValidationError) as excinfo:
        DeviceDefinition.model_validate(_modbus_payload(_registers(extra={"torque"})))
    assert "unknown signals: torque" in str(excinfo.value)


def test_unknown_top_level_key_is_rejected() -> None:
    payload = _modbus_payload(_registers())
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        DeviceDefinition.model_validate(payload)


def test_missing_protocol_block_is_rejected() -> None:
    payload = _modbus_payload(_registers())
    del payload["modbus_tcp"]
    with pytest.raises(ValidationError) as excinfo:
        DeviceDefinition.model_validate(payload)
    assert "must declare a 'modbus_tcp' block" in str(excinfo.value)


def test_mismatched_protocol_block_is_rejected() -> None:
    payload = _modbus_payload(_registers())
    payload["opc_ua"] = {
        "endpoint": "opc.tcp://localhost:4840/test/",
        "nodes": {signal: {"node_id": "ns=2;s=x"} for signal in CANONICAL_SIGNAL_FIELDS},
    }
    with pytest.raises(ValidationError) as excinfo:
        DeviceDefinition.model_validate(payload)
    assert "do not match protocol" in str(excinfo.value)


def test_opcua_endpoint_scheme_is_enforced() -> None:
    with pytest.raises(ValidationError) as excinfo:
        DeviceDefinition.model_validate(
            {
                "device_id": "MOTOR-002",
                "protocol": "opc_ua",
                "state": {"operating_state": "RUNNING", "fault_state": "NORMAL"},
                "opc_ua": {"endpoint": "http://localhost:4840/", "nodes": _nodes()},
            }
        )
    assert "opc.tcp://" in str(excinfo.value)


def _nodes() -> dict[str, Any]:
    return {signal: {"node_id": f"ns=2;s={signal}"} for signal in CANONICAL_SIGNAL_FIELDS}


def test_poll_interval_bounds_are_enforced() -> None:
    payload = _modbus_payload(_registers())
    payload["poll_interval_ms"] = 10
    with pytest.raises(ValidationError):
        DeviceDefinition.model_validate(payload)


def test_device_id_pattern_is_enforced() -> None:
    payload = _modbus_payload(_registers())
    payload["device_id"] = "bad id!"
    with pytest.raises(ValidationError):
        DeviceDefinition.model_validate(payload)


def test_state_labels_are_required() -> None:
    payload = _modbus_payload(_registers())
    del payload["state"]
    with pytest.raises(ValidationError):
        DeviceDefinition.model_validate(payload)


def test_state_defaults_to_static_mode() -> None:
    definition = DeviceDefinition.model_validate(_modbus_payload(_registers()))
    assert definition.state.mode == "static"
    assert definition.state.operating_state == "RUNNING"


def test_state_rule_requires_a_canonical_signal() -> None:
    with pytest.raises(ValidationError) as excinfo:
        StateRule.model_validate(
            {"target": "operating_state", "signal": "torque", "threshold": 1, "then": "X"}
        )
    assert "canonical signal" in str(excinfo.value)


@pytest.mark.parametrize(
    ("operator", "threshold", "measurement", "expected"),
    [
        ("eq", 0.0, 0.0, True),
        ("ne", 0.0, 1.0, True),
        ("gt", 7.0, 7.1, True),
        ("gte", 7.0, 7.0, True),
        ("lt", 7.0, 6.9, True),
        ("lte", 0.0, 0.0, True),
        ("gt", 7.0, 7.0, False),
        ("lt", 7.0, 7.0, False),
    ],
)
def test_state_rule_matching(
    operator: str, threshold: float, measurement: float, expected: bool
) -> None:
    rule = StateRule.model_validate(
        {
            "target": "operating_state",
            "signal": "rpm",
            "operator": operator,
            "threshold": threshold,
            "then": "X",
        }
    )
    assert rule.matches(measurement) is expected


def test_derived_mode_is_reported() -> None:
    payload = _modbus_payload(_registers())
    payload["state"] = {
        "operating_state": "RUNNING",
        "fault_state": "NORMAL",
        "derived": [
            {
                "target": "operating_state",
                "signal": "rpm",
                "operator": "lte",
                "threshold": 0,
                "then": "STOPPED",
            }
        ],
    }
    definition = DeviceDefinition.model_validate(payload)
    assert definition.state.mode == "derived"


def test_endpoint_describes_host_and_port_without_secrets() -> None:
    definition = DeviceDefinition.model_validate(_modbus_payload(_registers()))
    assert definition.endpoint == "localhost:5020"


def test_mqtt_is_not_polled() -> None:
    definition = DeviceDefinition.model_validate(
        {
            "device_id": "MQTT-001",
            "protocol": "mqtt",
            "state": {"operating_state": "RUNNING", "fault_state": "NORMAL"},
            "mqtt": {"topic": "industrial/devices/MQTT-001/telemetry"},
        }
    )
    assert definition.polled is False
    assert definition.endpoint is None


def test_enabled_defaults_to_true_and_honours_false() -> None:
    payload = _modbus_payload(_registers())
    assert DeviceDefinition.model_validate(payload).enabled is True
    payload["enabled"] = False
    assert DeviceDefinition.model_validate(payload).enabled is False
