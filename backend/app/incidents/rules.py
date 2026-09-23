"""Declarative alarm rule evaluation and rule definition validation.

This module holds the whole rule engine and it is deliberately pure. It reads a
mapping of canonical signal readings and a sequence of rule definitions, and it
returns breaches. It performs no I/O, opens no session, touches no device, and
calls no model, so a rule can never actuate anything and rule evaluation is
exhaustively unit testable without a database.

Two vocabularies meet here and the mapping between them is explicit rather than
inferred. The gateway and the rule registry name a signal without its unit
suffix (``temperature``, ``vibration``). The telemetry contract names the stored
column with it (``temperature_c``, ``vibration_mm_s``). ``SIGNAL_SPECS`` is the
one place that mapping, the physical range, and the unit label are declared, and
a test probes the telemetry contract at the boundaries to prove the declared
range still matches what ingestion accepts.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.incidents.models import (
    RULE_OPERATORS,
    RULE_PRIORITIES,
    RULE_SEVERITIES,
    RULE_SIGNAL_NAMES,
    AlarmRule,
)


@dataclass(frozen=True, slots=True)
class SignalSpec:
    """One canonical signal: its telemetry field, its range, and its unit."""

    canonical: str
    field: str
    low: float
    high: float
    unit: str


#: The single authority for the canonical-signal to telemetry-column mapping.
#: Ranges mirror the bounds the telemetry contract enforces on ingestion.
SIGNAL_SPECS: dict[str, SignalSpec] = {
    "temperature": SignalSpec("temperature", "temperature_c", -50.0, 250.0, "°C"),
    "bearing_temperature": SignalSpec(
        "bearing_temperature", "bearing_temperature_c", -50.0, 250.0, "°C"
    ),
    "vibration": SignalSpec("vibration", "vibration_mm_s", 0.0, 200.0, "mm/s"),
    "current": SignalSpec("current", "current_a", 0.0, 10_000.0, "A"),
    "voltage": SignalSpec("voltage", "voltage_v", 0.0, 10_000.0, "V"),
    "rpm": SignalSpec("rpm", "rpm", 0.0, 100_000.0, "rpm"),
    "load": SignalSpec("load", "load_pct", 0.0, 120.0, "%"),
    "power": SignalSpec("power", "power_kw", 0.0, 100_000.0, "kW"),
}

OPERATOR_SYMBOLS: dict[str, str] = {
    "GT": ">",
    "GTE": ">=",
    "LT": "<",
    "LTE": "<=",
    "EQ": "==",
    "NE": "!=",
}

#: Stable validation codes, so a rejected definition reports the same code
#: whichever entry point rejected it.
SIGNAL_UNKNOWN = "SIGNAL_UNKNOWN"
OPERATOR_UNKNOWN = "OPERATOR_UNKNOWN"
SEVERITY_UNKNOWN = "SEVERITY_UNKNOWN"
PRIORITY_UNKNOWN = "PRIORITY_UNKNOWN"
THRESHOLD_NOT_FINITE = "THRESHOLD_NOT_FINITE"
THRESHOLD_OUT_OF_RANGE = "THRESHOLD_OUT_OF_RANGE"
NAME_REQUIRED = "NAME_REQUIRED"
RULE_ID_INVALID = "RULE_ID_INVALID"
DEVICE_TYPE_INVALID = "DEVICE_TYPE_INVALID"

_MAX_RULE_ID = 100
_MAX_NAME = 200
_RULE_ID_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def _issue(field_path: str, code: str, message: str) -> dict[str, str]:
    return {"field": field_path, "code": code, "message": message}


def _format_number(value: float) -> str:
    """Render a float compactly, dropping a trailing ``.0`` for whole numbers."""

    return f"{value:g}"


def compare(operator: str, value: float, threshold: float) -> bool:
    """Return whether ``value`` satisfies ``operator threshold``."""

    if operator == "GT":
        return value > threshold
    if operator == "GTE":
        return value >= threshold
    if operator == "LT":
        return value < threshold
    if operator == "LTE":
        return value <= threshold
    if operator == "EQ":
        return value == threshold
    if operator == "NE":
        return value != threshold
    raise ValueError(f"unsupported alarm rule operator: {operator!r}")


def canonical_readings(payload: Mapping[str, Any]) -> dict[str, float]:
    """Project a telemetry payload onto the canonical signal names.

    A missing key is omitted rather than defaulted. A defaulted reading would
    fabricate a measurement and could fire a rule on a value that was never
    observed.
    """

    readings: dict[str, float] = {}
    for spec in SIGNAL_SPECS.values():
        raw = payload.get(spec.field)
        if raw is None:
            continue
        readings[spec.canonical] = float(raw)
    return readings


def render_message(spec: SignalSpec, operator: str, threshold: float, value: float) -> str:
    """Render the human-readable alarm message.

    The observed value is included, which the two rules replaced by this phase
    did not do. ``High temperature: 95.2 °C > 90 °C`` states the breach and the
    measurement in one line.
    """

    symbol = OPERATOR_SYMBOLS[operator]
    unit = spec.unit
    return f"{_format_number(value)} {unit} {symbol} {_format_number(threshold)} {unit}"


@dataclass(frozen=True, slots=True)
class RuleBreach:
    """One rule that a single telemetry reading satisfied."""

    rule_id: str
    rule_name: str
    signal_name: str
    operator: str
    threshold: float
    observed: float
    severity: str
    priority: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "signal_name": self.signal_name,
            "operator": self.operator,
            "threshold": self.threshold,
            "observed": self.observed,
            "severity": self.severity,
            "priority": self.priority,
            "message": self.message,
        }


def evaluate_rules(
    rules: Iterable[AlarmRule],
    readings: Mapping[str, float],
    *,
    device_type: str | None = None,
) -> list[RuleBreach]:
    """Return one breach per enabled, applicable rule that the readings satisfy.

    Rules are expected to arrive in a deterministic order from the repository, so
    the returned list is deterministic too. A disabled rule is skipped, a rule
    scoped to another device type is skipped, and a rule whose signal is absent
    from the readings is skipped.
    """

    breaches: list[RuleBreach] = []
    for rule in rules:
        if not rule.enabled:
            continue
        if rule.device_type is not None and rule.device_type != device_type:
            continue
        spec = SIGNAL_SPECS.get(rule.signal_name)
        if spec is None:
            continue
        observed = readings.get(rule.signal_name)
        if observed is None:
            continue
        if not compare(rule.operator, observed, rule.threshold):
            continue
        breaches.append(
            RuleBreach(
                rule_id=rule.id,
                rule_name=rule.name,
                signal_name=rule.signal_name,
                operator=rule.operator,
                threshold=rule.threshold,
                observed=observed,
                severity=rule.severity,
                priority=rule.priority,
                message=render_message(spec, rule.operator, rule.threshold, observed),
            )
        )
    return breaches


def validate_rule_definition(
    *,
    rule_id: str | None,
    name: str | None,
    signal_name: str | None,
    operator: str | None,
    threshold: float | None,
    severity: str | None,
    priority: str | None,
    device_type: str | None = None,
) -> list[dict[str, str]]:
    """Return structured issues for an unusable rule definition.

    An empty list means the definition may be persisted. A rule that is merely
    disabled is valid: disabling is how a rule is retired without deleting the
    history that references it.

    Every argument is optional so the same function validates a creation and a
    patch that was merged onto an existing row. An explicit null is rejected
    rather than treated as an absent field, because a null threshold or a null
    signal would store a rule that can never be evaluated correctly.
    """

    issues: list[dict[str, str]] = []

    if not rule_id or len(rule_id) > _MAX_RULE_ID or not set(rule_id) <= _RULE_ID_ALLOWED:
        issues.append(
            _issue(
                "id",
                RULE_ID_INVALID,
                f"rule id must be 1 to {_MAX_RULE_ID} characters drawn from letters, "
                "digits, dot, underscore, or hyphen",
            )
        )

    if not name or not name.strip() or len(name) > _MAX_NAME:
        issues.append(_issue("name", NAME_REQUIRED, f"name must be 1 to {_MAX_NAME} characters"))

    if signal_name not in RULE_SIGNAL_NAMES:
        issues.append(
            _issue(
                "signal_name",
                SIGNAL_UNKNOWN,
                f"signal must be one of {', '.join(RULE_SIGNAL_NAMES)}",
            )
        )

    if operator not in RULE_OPERATORS:
        issues.append(
            _issue(
                "operator",
                OPERATOR_UNKNOWN,
                f"operator must be one of {', '.join(RULE_OPERATORS)}",
            )
        )

    if severity not in RULE_SEVERITIES:
        issues.append(
            _issue(
                "severity",
                SEVERITY_UNKNOWN,
                f"severity must be one of {', '.join(RULE_SEVERITIES)}",
            )
        )

    if priority not in RULE_PRIORITIES:
        issues.append(
            _issue(
                "priority",
                PRIORITY_UNKNOWN,
                f"priority must be one of {', '.join(RULE_PRIORITIES)}",
            )
        )

    spec = SIGNAL_SPECS.get(signal_name) if signal_name is not None else None
    if threshold is None or not math.isfinite(threshold):
        issues.append(
            _issue(
                "threshold",
                THRESHOLD_NOT_FINITE,
                "threshold must be a finite number",
            )
        )
    elif spec is not None and not (spec.low <= threshold <= spec.high):
        issues.append(
            _issue(
                "threshold",
                THRESHOLD_OUT_OF_RANGE,
                f"threshold for signal {signal_name!r} must lie within "
                f"{_format_number(spec.low)} to {_format_number(spec.high)} {spec.unit}",
            )
        )

    if device_type is not None and not device_type.strip():
        issues.append(_issue("device_type", DEVICE_TYPE_INVALID, "device_type must not be blank"))

    return issues


__all__ = [
    "OPERATOR_SYMBOLS",
    "SIGNAL_SPECS",
    "RuleBreach",
    "SignalSpec",
    "canonical_readings",
    "compare",
    "evaluate_rules",
    "render_message",
    "validate_rule_definition",
]
