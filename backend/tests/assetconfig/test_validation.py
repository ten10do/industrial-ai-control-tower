"""Validation pipeline coverage.

Every check here is side-effect free by construction: the pipeline takes a device
status string and a payload, and returns structured issues. Nothing is published,
nothing is stored, and no endpoint is contacted.
"""

from __future__ import annotations

import pytest

from app.assetconfig.validation import (
    DEVICE_ID_MISMATCH,
    DEVICE_NOT_ACTIVE,
    DEVICE_NOT_FOUND,
    ENDPOINT_INVALID,
    FIELD_REQUIRED,
    FIELD_UNKNOWN,
    MISSING_SIGNAL,
    PROTOCOL_BLOCK_MISMATCH,
    PROTOCOL_BLOCK_MISSING,
    SECRET_MATERIAL_REJECTED,
    STATE_RULE_INVALID,
    UNKNOWN_SIGNAL,
    validate_configuration,
)
from app.gateway.models import CANONICAL_SIGNAL_FIELDS
from tests.assetconfig.conftest import modbus_payload, opcua_payload


def _codes(outcome: object) -> set[str]:
    return {issue["code"] for issue in outcome.errors}  # type: ignore[attr-defined]


def _fields(outcome: object) -> set[str]:
    return {issue["field"] for issue in outcome.errors}  # type: ignore[attr-defined]


def test_a_complete_definition_is_valid() -> None:
    outcome = validate_configuration(
        device_id="MOTOR-001", payload=modbus_payload(), device_status="ACTIVE"
    )
    assert outcome.valid is True
    assert outcome.errors == []
    assert outcome.checked_at.tzinfo is not None


def test_missing_canonical_signal_is_rejected() -> None:
    payload = modbus_payload()
    del payload["modbus_tcp"]["registers"]["temperature"]
    outcome = validate_configuration(device_id="MOTOR-001", payload=payload, device_status="ACTIVE")
    assert outcome.valid is False
    assert MISSING_SIGNAL in _codes(outcome)


def test_unknown_signal_is_rejected() -> None:
    payload = modbus_payload()
    payload["modbus_tcp"]["registers"]["torque"] = {"address": 40099, "scale": 1.0, "unit": None}
    outcome = validate_configuration(device_id="MOTOR-001", payload=payload, device_status="ACTIVE")
    assert outcome.valid is False
    assert UNKNOWN_SIGNAL in _codes(outcome)


def test_partial_signal_coverage_reports_every_missing_signal() -> None:
    payload = modbus_payload()
    payload["modbus_tcp"]["registers"] = {
        "temperature": {"address": 40001, "scale": 1.0, "unit": None}
    }
    outcome = validate_configuration(device_id="MOTOR-001", payload=payload, device_status="ACTIVE")
    assert outcome.valid is False
    missing = set(CANONICAL_SIGNAL_FIELDS) - {"temperature"}
    message = " ".join(issue["message"] for issue in outcome.errors)
    for signal in missing:
        assert signal in message


def test_invalid_modbus_register_mapping_is_rejected() -> None:
    payload = modbus_payload()
    payload["modbus_tcp"]["registers"]["vibration"]["address"] = 123
    outcome = validate_configuration(device_id="MOTOR-001", payload=payload, device_status="ACTIVE")
    assert outcome.valid is False


def test_invalid_opcua_endpoint_is_rejected() -> None:
    payload = opcua_payload()
    payload["opc_ua"]["endpoint"] = "http://localhost:4840/x"
    outcome = validate_configuration(device_id="MOTOR-003", payload=payload, device_status="ACTIVE")
    assert outcome.valid is False
    assert ENDPOINT_INVALID in _codes(outcome)


def test_protocol_block_mismatch_is_rejected() -> None:
    payload = modbus_payload()
    payload["opc_ua"] = opcua_payload()["opc_ua"]
    outcome = validate_configuration(device_id="MOTOR-001", payload=payload, device_status="ACTIVE")
    assert outcome.valid is False
    assert PROTOCOL_BLOCK_MISMATCH in _codes(outcome)


def test_missing_protocol_block_is_rejected() -> None:
    payload = modbus_payload()
    del payload["modbus_tcp"]
    outcome = validate_configuration(device_id="MOTOR-001", payload=payload, device_status="ACTIVE")
    assert outcome.valid is False
    assert PROTOCOL_BLOCK_MISSING in _codes(outcome)


@pytest.mark.parametrize("interval", [0, 99, 3_600_001])
def test_invalid_poll_interval_is_rejected(interval: int) -> None:
    outcome = validate_configuration(
        device_id="MOTOR-001",
        payload=modbus_payload(poll_interval_ms=interval),
        device_status="ACTIVE",
    )
    assert outcome.valid is False


def test_invalid_timeout_is_rejected() -> None:
    payload = modbus_payload()
    payload["modbus_tcp"]["timeout_seconds"] = 0
    outcome = validate_configuration(device_id="MOTOR-001", payload=payload, device_status="ACTIVE")
    assert outcome.valid is False


def test_unknown_top_level_field_is_rejected() -> None:
    payload = modbus_payload()
    payload["retry_policy"] = {"max": 3}
    outcome = validate_configuration(device_id="MOTOR-001", payload=payload, device_status="ACTIVE")
    assert outcome.valid is False
    assert FIELD_UNKNOWN in _codes(outcome)


def test_device_id_mismatch_is_rejected() -> None:
    outcome = validate_configuration(
        device_id="MOTOR-002", payload=modbus_payload("MOTOR-001"), device_status="ACTIVE"
    )
    assert outcome.valid is False
    assert DEVICE_ID_MISMATCH in _codes(outcome)


def test_unregistered_device_is_rejected() -> None:
    outcome = validate_configuration(
        device_id="MOTOR-001", payload=modbus_payload(), device_status=None
    )
    assert outcome.valid is False
    assert DEVICE_NOT_FOUND in _codes(outcome)


@pytest.mark.parametrize("status", ["INACTIVE", "DECOMMISSIONED"])
def test_inactive_device_cannot_be_onboarded(status: str) -> None:
    outcome = validate_configuration(
        device_id="MOTOR-001", payload=modbus_payload(), device_status=status
    )
    assert outcome.valid is False
    assert DEVICE_NOT_ACTIVE in _codes(outcome)


def test_secret_like_field_is_rejected() -> None:
    payload = modbus_payload()
    payload["modbus_tcp"]["broker_password"] = "hunter2"
    outcome = validate_configuration(device_id="MOTOR-001", payload=payload, device_status="ACTIVE")
    assert outcome.valid is False
    assert SECRET_MATERIAL_REJECTED in _codes(outcome)
    assert "hunter2" not in " ".join(issue["message"] for issue in outcome.errors)


def test_secret_reference_field_is_rejected() -> None:
    """No protocol block declares a credential field, so a reference is not accepted.

    The spec allows an opaque ``credential_ref`` shape in principle, but implementing a
    field that nothing consumes would be a promise the phase does not keep. Until a
    real secret backend exists, any credential-shaped key is refused outright.
    """

    payload = opcua_payload()
    payload["opc_ua"]["credential_ref"] = "opcua/site-a/motor-003"
    outcome = validate_configuration(device_id="MOTOR-003", payload=payload, device_status="ACTIVE")
    assert outcome.valid is False
    assert FIELD_UNKNOWN in _codes(outcome)

    payload["opc_ua"]["credential_ref"] = ""
    outcome = validate_configuration(device_id="MOTOR-003", payload=payload, device_status="ACTIVE")
    assert outcome.valid is False
    assert FIELD_UNKNOWN in _codes(outcome)


def test_state_derivation_rule_requires_a_canonical_signal() -> None:
    payload = modbus_payload()
    payload["state"]["derived"] = [
        {"target": "fault_state", "signal": "torque", "operator": "gt", "threshold": 5, "then": "X"}
    ]
    outcome = validate_configuration(device_id="MOTOR-001", payload=payload, device_status="ACTIVE")
    assert outcome.valid is False
    assert STATE_RULE_INVALID in _codes(outcome)


def test_missing_required_field_is_reported_as_required() -> None:
    payload = modbus_payload()
    del payload["state"]
    outcome = validate_configuration(device_id="MOTOR-001", payload=payload, device_status="ACTIVE")
    assert outcome.valid is False
    assert FIELD_REQUIRED in _codes(outcome)
    assert "state" in _fields(outcome)


def test_validation_never_returns_a_bare_message() -> None:
    """Every issue carries a field, a code, and a message."""

    payload = modbus_payload()
    del payload["modbus_tcp"]["registers"]["power"]
    payload["protocol"] = "profibus"
    outcome = validate_configuration(device_id="MOTOR-001", payload=payload, device_status="ACTIVE")
    assert outcome.errors
    for issue in outcome.errors:
        assert set(issue) == {"field", "code", "message"}
        assert issue["code"]
        assert issue["field"]
        assert issue["message"]
