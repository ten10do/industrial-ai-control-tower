"""Normalize adapter telemetry into the canonical ingestion contract.

The Phase 6.5 adapters emit ``UnifiedTelemetry``, whose ``signals`` mapping uses the
canonical signal vocabulary and float values. The ingestion boundary expects the
flat simulator-compatible contract, whose ``rpm`` field is an integer and whose two
state fields are strings. This module is the single place that bridges the two.

No field is ever defaulted. A sample that cannot supply every canonical signal is
rejected instead of being filled with a guess.
"""

from __future__ import annotations

import json
from typing import Any

from adapters.models import UnifiedTelemetry
from app.gateway.errors import TelemetryNormalizationError
from app.gateway.models import DeviceStateDefinition

SIGNAL_TO_CONTRACT_FIELD: dict[str, str] = {
    "temperature": "temperature_c",
    "bearing_temperature": "bearing_temperature_c",
    "vibration": "vibration_mm_s",
    "current": "current_a",
    "voltage": "voltage_v",
    "rpm": "rpm",
    "load": "load_pct",
    "power": "power_kw",
}

_INTEGER_CONTRACT_FIELDS = frozenset({"rpm"})

SCHEMA_VERSION = "1.0"


def resolve_state(definition: DeviceStateDefinition, signals: dict[str, float]) -> tuple[str, str]:
    """Resolve the state labels for one sample.

    Derived rules are consulted first, in declaration order, and the first rule that
    matches a target wins for that target independently. Targets without a matching
    rule fall back to their static configured label.
    """

    resolved: dict[str, str] = {
        "operating_state": definition.operating_state,
        "fault_state": definition.fault_state,
    }
    settled: set[str] = set()
    for rule in definition.derived:
        if rule.target in settled:
            continue
        measurement = signals.get(rule.signal)
        if measurement is None:
            continue
        if rule.matches(measurement):
            resolved[rule.target] = rule.then
            settled.add(rule.target)
    return resolved["operating_state"], resolved["fault_state"]


def to_canonical_payload(
    telemetry: UnifiedTelemetry, definition: DeviceStateDefinition
) -> dict[str, Any]:
    """Build the canonical ingestion payload for one adapter sample."""

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": telemetry.timestamp.isoformat(),
        "device_id": telemetry.device_id,
    }
    missing: list[str] = []
    for signal, field in SIGNAL_TO_CONTRACT_FIELD.items():
        measurement = telemetry.signals.get(signal)
        if measurement is None:
            missing.append(signal)
            continue
        payload[field] = (
            int(round(measurement)) if field in _INTEGER_CONTRACT_FIELDS else float(measurement)
        )
    if missing:
        raise TelemetryNormalizationError(
            "adapter sample is missing canonical signals: " + ", ".join(sorted(missing))
        )
    operating_state, fault_state = resolve_state(definition, telemetry.signals)
    payload["operating_state"] = operating_state
    payload["fault_state"] = fault_state
    return payload


def to_canonical_body(telemetry: UnifiedTelemetry, definition: DeviceStateDefinition) -> bytes:
    """Serialize one adapter sample into the canonical request body."""

    return json.dumps(to_canonical_payload(telemetry, definition)).encode("utf-8")
