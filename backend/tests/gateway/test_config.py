"""Gateway configuration loading and secret redaction."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.gateway.config import is_secret_key, load_gateway_config, redact_secrets
from app.gateway.errors import GatewayConfigurationError

VALID = """
version: 1
devices:
  - device_id: MOTOR-001
    protocol: mqtt
    state:
      operating_state: RUNNING
      fault_state: NORMAL
    mqtt:
      topic: industrial/devices/MOTOR-001/telemetry
"""


def _write(tmp_path: Path, text: str, name: str = "gateway_devices.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_configuration_loads(tmp_path: Path) -> None:
    definitions = load_gateway_config(_write(tmp_path, VALID))
    assert [definition.device_id for definition in definitions] == ["MOTOR-001"]


def test_missing_file_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(GatewayConfigurationError) as excinfo:
        load_gateway_config(tmp_path / "absent.yaml")
    assert "absent.yaml" in str(excinfo.value)


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(GatewayConfigurationError) as excinfo:
        load_gateway_config(_write(tmp_path, "\n"))
    assert "empty" in str(excinfo.value)


def test_non_mapping_document_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(GatewayConfigurationError) as excinfo:
        load_gateway_config(_write(tmp_path, "- a\n- b\n"))
    assert "must be a mapping" in str(excinfo.value)


def test_malformed_yaml_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(GatewayConfigurationError) as excinfo:
        load_gateway_config(_write(tmp_path, "devices: [\n"))
    assert "not valid YAML" in str(excinfo.value)


def test_unknown_version_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(GatewayConfigurationError) as excinfo:
        load_gateway_config(_write(tmp_path, "version: 99\ndevices: []\n"))
    assert "unsupported gateway configuration version" in str(excinfo.value)


def test_unknown_top_level_key_is_rejected(tmp_path: Path) -> None:
    text = "version: 1\ndevices: []\nextra: true\n"
    with pytest.raises(GatewayConfigurationError) as excinfo:
        load_gateway_config(_write(tmp_path, text))
    assert "invalid gateway configuration" in str(excinfo.value)


def test_partial_signal_coverage_is_rejected(tmp_path: Path) -> None:
    text = """
version: 1
devices:
  - device_id: MOTOR-001
    protocol: modbus_tcp
    state:
      operating_state: RUNNING
      fault_state: NORMAL
    modbus_tcp:
      host: localhost
      port: 5020
      registers:
        temperature:
          address: 40001
          scale: 0.1
"""
    with pytest.raises(GatewayConfigurationError) as excinfo:
        load_gateway_config(_write(tmp_path, text))
    assert "missing canonical signals" in str(excinfo.value)


@pytest.mark.parametrize(
    "key",
    ["password", "OPC_PASSWORD", "api_key", "auth_token", "client_secret", "private_key"],
)
def test_secret_keys_are_detected(key: str) -> None:
    assert is_secret_key(key) is True


@pytest.mark.parametrize("key", ["host", "port", "endpoint", "node_id", "poll_interval_ms"])
def test_non_secret_keys_are_not_flagged(key: str) -> None:
    assert is_secret_key(key) is False


def test_redaction_is_recursive_and_shape_preserving() -> None:
    document = {
        "host": "localhost",
        "password": "hunter2",
        "nested": {"api_key": "abc", "port": 502, "deep": [{"token": "t"}]},
    }
    redacted = redact_secrets(document)
    assert redacted == {
        "host": "localhost",
        "password": "***REDACTED***",
        "nested": {
            "api_key": "***REDACTED***",
            "port": 502,
            "deep": [{"token": "***REDACTED***"}],
        },
    }
    assert document["password"] == "hunter2"
