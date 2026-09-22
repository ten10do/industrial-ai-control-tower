"""Normalization from adapter telemetry to the canonical ingestion contract.

The last two tests in this module are equivalence checks: they prove the gateway's
payload and topic are accepted by the real ingestion boundary, so the gateway cannot
silently drift away from the contract it reuses.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from adapters.models import ProtocolType, SignalQuality, UnifiedTelemetry
from app.gateway.errors import TelemetryNormalizationError
from app.gateway.ingestion import telemetry_topic
from app.gateway.models import CANONICAL_SIGNAL_FIELDS
from app.gateway.normalizer import (
    SIGNAL_TO_CONTRACT_FIELD,
    resolve_state,
    to_canonical_body,
    to_canonical_payload,
)
from app.schemas.telemetry import TelemetryIn
from app.services.telemetry import TelemetryService
from tests.gateway.conftest import BASE_SIGNALS, sample, state_definition


def test_every_canonical_signal_maps_to_a_contract_field() -> None:
    payload = to_canonical_payload(sample(), state_definition())
    for field in SIGNAL_TO_CONTRACT_FIELD.values():
        assert field in payload
    assert set(SIGNAL_TO_CONTRACT_FIELD) == set(CANONICAL_SIGNAL_FIELDS)


def test_rpm_is_coerced_to_an_integer() -> None:
    payload = to_canonical_payload(sample(rpm=1440.6), state_definition())
    assert payload["rpm"] == 1441
    assert isinstance(payload["rpm"], int)


def test_body_is_json_encodable_and_carries_the_device_id() -> None:
    body = to_canonical_body(sample(), state_definition())
    decoded = json.loads(body)
    assert decoded["device_id"] == "MOTOR-001"
    assert decoded["schema_version"] == "1.0"


def test_missing_signal_is_rejected_rather_than_defaulted() -> None:
    incomplete = UnifiedTelemetry(
        device_id="MOTOR-001",
        timestamp=datetime.now(UTC),
        signals={key: value for key, value in BASE_SIGNALS.items() if key != "voltage"},
        source_protocol=ProtocolType.MODBUS_TCP,
        quality=SignalQuality.GOOD,
    )
    with pytest.raises(TelemetryNormalizationError) as excinfo:
        to_canonical_payload(incomplete, state_definition())
    assert "voltage" in str(excinfo.value)


def test_unmapped_extra_signals_are_not_forwarded() -> None:
    payload = to_canonical_payload(sample(torque=12.5), state_definition())
    assert "torque" not in payload


def test_static_labels_are_used_without_rules() -> None:
    definition = state_definition(operating_state="IDLE", fault_state="UNKNOWN")
    assert resolve_state(definition, BASE_SIGNALS) == ("IDLE", "UNKNOWN")


def test_derived_rule_overrides_the_static_label_on_match() -> None:
    definition = state_definition(
        derived=[
            {
                "target": "operating_state",
                "signal": "rpm",
                "operator": "lte",
                "threshold": 0,
                "then": "STOPPED",
            }
        ]
    )
    assert resolve_state(definition, {**BASE_SIGNALS, "rpm": 0.0}) == ("STOPPED", "NORMAL")
    assert resolve_state(definition, {**BASE_SIGNALS, "rpm": 1440.0}) == ("RUNNING", "NORMAL")


def test_targets_are_resolved_independently() -> None:
    definition = state_definition(
        derived=[
            {
                "target": "operating_state",
                "signal": "rpm",
                "operator": "lte",
                "threshold": 0,
                "then": "STOPPED",
            },
            {
                "target": "fault_state",
                "signal": "vibration",
                "operator": "gt",
                "threshold": 7,
                "then": "HIGH_VIBRATION",
            },
        ]
    )
    assert resolve_state(definition, {**BASE_SIGNALS, "rpm": 0.0, "vibration": 9.0}) == (
        "STOPPED",
        "HIGH_VIBRATION",
    )


def test_first_matching_rule_per_target_wins() -> None:
    definition = state_definition(
        derived=[
            {
                "target": "operating_state",
                "signal": "rpm",
                "operator": "gt",
                "threshold": 1,
                "then": "FIRST",
            },
            {
                "target": "operating_state",
                "signal": "rpm",
                "operator": "gt",
                "threshold": 1,
                "then": "SECOND",
            },
        ]
    )
    assert resolve_state(definition, BASE_SIGNALS)[0] == "FIRST"


def test_rule_on_an_absent_signal_is_skipped() -> None:
    definition = state_definition(
        derived=[
            {
                "target": "operating_state",
                "signal": "voltage",
                "operator": "lt",
                "threshold": 100,
                "then": "BROWNOUT",
            }
        ]
    )
    signals = {key: value for key, value in BASE_SIGNALS.items() if key != "voltage"}
    assert resolve_state(definition, signals)[0] == "RUNNING"


def test_payload_is_accepted_by_the_real_ingestion_contract() -> None:
    payload = to_canonical_payload(sample(), state_definition())
    model = TelemetryIn.model_validate(payload)
    assert model.device_id == "MOTOR-001"
    assert model.rpm == 1440
    assert model.operating_state == "RUNNING"
    assert model.fault_state == "NORMAL"


def test_topic_matches_the_ingestion_topic_parser() -> None:
    topic = telemetry_topic("MOTOR-001")
    assert topic == "industrial/devices/MOTOR-001/telemetry"
    assert TelemetryService._topic_device_id(topic) == "MOTOR-001"


def test_topic_device_id_agrees_with_the_payload_device_id() -> None:
    telemetry = sample()
    payload = to_canonical_payload(telemetry, state_definition())
    assert (
        TelemetryService._topic_device_id(telemetry_topic(telemetry.device_id))
        == payload["device_id"]
    )
