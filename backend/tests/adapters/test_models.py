"""Unified telemetry model tests."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from adapters.models import ProtocolType, SignalQuality, UnifiedTelemetry


def test_json_payload_becomes_unified_telemetry() -> None:
    telemetry = UnifiedTelemetry.model_validate_json(
        """{
            "device_id": "MOTOR-001",
            "timestamp": "2026-09-22T10:00:00Z",
            "signals": {
                "temperature": 68.5,
                "vibration": 7.2,
                "current": 12.4,
                "rpm": 1480
            },
            "source_protocol": "mqtt",
            "quality": "GOOD",
            "metadata": {"location": "line-1"}
        }"""
    )

    assert telemetry.device_id == "MOTOR-001"
    assert telemetry.timestamp == datetime(2026, 9, 22, 10, tzinfo=UTC)
    assert telemetry.source_protocol is ProtocolType.MQTT
    assert telemetry.quality is SignalQuality.GOOD
    assert telemetry.signals["vibration"] == 7.2
    assert telemetry.metadata == {"location": "line-1"}


@pytest.mark.parametrize(
    "patch",
    [
        {"timestamp": "2026-09-22T10:00:00"},
        {"signals": {}},
        {"signals": {"temperature": float("inf")}},
        {"quality": "UNKNOWN"},
    ],
)
def test_unified_telemetry_rejects_invalid_data(patch: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "device_id": "MOTOR-001",
        "timestamp": "2026-09-22T10:00:00Z",
        "signals": {"temperature": 68.5},
        "source_protocol": "simulator",
        "quality": "GOOD",
        "metadata": {},
    }
    payload.update(patch)

    with pytest.raises(ValidationError):
        UnifiedTelemetry.model_validate(payload)
