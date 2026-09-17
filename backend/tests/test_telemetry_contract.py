"""Contract tests protecting simulator/backend schema compatibility."""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.device import DeviceUpdate
from app.schemas.telemetry import TelemetryIn

SIMULATOR_ROOT = Path(__file__).resolve().parents[2] / "simulator"
sys.path.insert(0, str(SIMULATOR_ROOT))
import simulator.models as simulator_models  # type: ignore[import-not-found]  # noqa: E402


def valid_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "timestamp": "2026-09-17T08:00:00+08:00",
        "device_id": "MOTOR-001",
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


def test_backend_and_simulator_field_contract_match() -> None:
    assert set(TelemetryIn.model_fields) == set(simulator_models.Telemetry.model_fields)


def test_timestamp_is_normalized_to_utc() -> None:
    telemetry = TelemetryIn.model_validate(valid_payload())
    assert telemetry.timestamp == datetime(2026, 9, 17, tzinfo=UTC)
    assert telemetry.timestamp.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    ("field", "value"),
    [("schema_version", "2.0"), ("load_pct", 121), ("vibration_mm_s", -1)],
)
def test_unsupported_or_impossible_values_are_rejected(field: str, value: object) -> None:
    payload = valid_payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        TelemetryIn.model_validate(payload)


def test_naive_timestamp_and_unknown_fields_are_rejected() -> None:
    payload = valid_payload()
    payload["timestamp"] = "2026-09-17T08:00:00"
    payload["unexpected"] = "drift"
    with pytest.raises(ValidationError):
        TelemetryIn.model_validate(payload)


def test_device_patch_rejects_explicit_null() -> None:
    with pytest.raises(ValidationError):
        DeviceUpdate.model_validate({"status": None})
