"""Declarative alarm rule evaluation and rule definition validation.

Everything here is pure. The rule engine reads a mapping of readings and a
sequence of rule definitions and returns breaches, so it is exercised without a
database, a session, or a device.
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.gateway.models import CANONICAL_SIGNAL_FIELDS
from app.incidents.models import RULE_OPERATORS, AlarmRule
from app.incidents.rules import (
    OPERATOR_SYMBOLS,
    SIGNAL_SPECS,
    canonical_readings,
    compare,
    evaluate_rules,
    render_message,
    validate_rule_definition,
)
from app.schemas.telemetry import TelemetryIn
from tests.incidents.conftest import telemetry_payload


def rule(
    rule_id: str = "temperature_high",
    *,
    name: str = "High temperature",
    signal_name: str = "temperature",
    operator: str = "GT",
    threshold: float = 90.0,
    severity: str = "CRITICAL",
    priority: str = "URGENT",
    enabled: bool = True,
    device_type: str | None = None,
) -> AlarmRule:
    """Build a rule without a session. ORM instances are plain Python objects."""

    return AlarmRule(
        id=rule_id,
        name=name,
        description="",
        device_type=device_type,
        signal_name=signal_name,
        operator=operator,
        threshold=threshold,
        severity=severity,
        priority=priority,
        enabled=enabled,
    )


def readings(**values: float) -> dict[str, float]:
    return dict(values)


def test_signal_specs_cover_every_canonical_signal_exactly() -> None:
    assert set(SIGNAL_SPECS) == set(CANONICAL_SIGNAL_FIELDS)


def test_signal_specs_name_fields_the_telemetry_contract_actually_has() -> None:
    contract_fields = set(TelemetryIn.model_fields)
    for spec in SIGNAL_SPECS.values():
        assert spec.field in contract_fields, spec.canonical


@pytest.mark.parametrize("canonical", sorted(SIGNAL_SPECS))
def test_declared_range_matches_what_the_telemetry_contract_enforces(canonical: str) -> None:
    """Probe the contract at each boundary so the declared range cannot drift.

    The rule engine rejects an out-of-range threshold using ``SIGNAL_SPECS``. If
    ingestion later widened a bound and this table was not updated, a rule could
    be rejected for naming a threshold the platform genuinely accepts.
    """

    spec = SIGNAL_SPECS[canonical]

    for value in (spec.low, spec.high):
        payload = {**telemetry_payload(), spec.field: value}
        TelemetryIn.model_validate(payload)

    for value in (spec.low - 1.0, spec.high + 1.0):
        payload = {**telemetry_payload(), spec.field: value}
        with pytest.raises(ValidationError):
            TelemetryIn.model_validate(payload)


def test_operator_symbols_cover_every_declared_operator() -> None:
    assert set(OPERATOR_SYMBOLS) == set(RULE_OPERATORS)


@pytest.mark.parametrize(
    ("operator", "value", "threshold", "expected"),
    [
        ("GT", 90.1, 90.0, True),
        ("GT", 90.0, 90.0, False),
        ("GTE", 90.0, 90.0, True),
        ("GTE", 89.9, 90.0, False),
        ("LT", 89.9, 90.0, True),
        ("LT", 90.0, 90.0, False),
        ("LTE", 90.0, 90.0, True),
        ("LTE", 90.1, 90.0, False),
        ("EQ", 90.0, 90.0, True),
        ("EQ", 90.1, 90.0, False),
        ("NE", 90.1, 90.0, True),
        ("NE", 90.0, 90.0, False),
    ],
)
def test_compare_covers_every_operator_at_the_boundary(
    operator: str, value: float, threshold: float, expected: bool
) -> None:
    assert compare(operator, value, threshold) is expected


def test_compare_refuses_an_unknown_operator() -> None:
    with pytest.raises(ValueError):
        compare("APPROX", 1.0, 1.0)


def test_a_threshold_breach_fires_strictly_above_the_limit() -> None:
    temperature_high = rule(threshold=90.0)

    assert evaluate_rules([temperature_high], readings(temperature=90.0)) == []
    breach = evaluate_rules([temperature_high], readings(temperature=90.1))
    assert len(breach) == 1
    assert breach[0].rule_id == "temperature_high"
    assert breach[0].observed == 90.1
    assert breach[0].threshold == 90.0


def test_a_disabled_rule_never_fires() -> None:
    """Disabling is how a rule is retired without deleting its history."""

    disabled = rule(enabled=False)
    assert evaluate_rules([disabled], readings(temperature=200.0)) == []


def test_a_rule_scoped_to_another_device_type_never_fires() -> None:
    scoped = rule(device_type="PUMP")

    assert evaluate_rules([scoped], readings(temperature=200.0), device_type="MOTOR") == []
    assert len(evaluate_rules([scoped], readings(temperature=200.0), device_type="PUMP")) == 1


def test_a_global_rule_fires_for_any_device_type() -> None:
    global_rule = rule(device_type=None)

    assert len(evaluate_rules([global_rule], readings(temperature=200.0), device_type="MOTOR")) == 1
    assert len(evaluate_rules([global_rule], readings(temperature=200.0))) == 1


def test_a_rule_whose_signal_is_absent_from_the_readings_never_fires() -> None:
    """A missing reading is omitted rather than defaulted.

    Defaulting would fabricate a measurement and could fire a rule on a value
    that was never observed.
    """

    assert evaluate_rules([rule()], readings(vibration=1.0)) == []


def test_evaluation_order_follows_the_order_the_rules_arrive_in() -> None:
    """Determinism is what makes the resulting alarm set reproducible."""

    rules = [
        rule("a_rule", threshold=10.0),
        rule("b_rule", threshold=20.0),
        rule("c_rule", threshold=30.0),
    ]
    breaches = evaluate_rules(rules, readings(temperature=100.0))
    assert [breach.rule_id for breach in breaches] == ["a_rule", "b_rule", "c_rule"]


def test_severity_and_priority_come_from_the_rule() -> None:
    breach = evaluate_rules([rule(severity="MAJOR", priority="HIGH")], readings(temperature=95.0))[
        0
    ]
    assert breach.severity == "MAJOR"
    assert breach.priority == "HIGH"


def test_every_parameterized_boundary_case_is_absorbed_by_the_range_check() -> None:
    """A rule whose threshold is outside the signal range cannot be created."""

    for canonical, spec in SIGNAL_SPECS.items():
        assert math.isfinite(spec.low)
        assert math.isfinite(spec.high)
        assert spec.low <= spec.high, canonical


def test_canonical_readings_maps_telemetry_columns_onto_canonical_names() -> None:
    projected = canonical_readings(telemetry_payload(temperature_c=91.5, vibration_mm_s=8.25))

    assert projected["temperature"] == 91.5
    assert projected["vibration"] == 8.25
    assert set(projected) == set(SIGNAL_SPECS)


def test_canonical_readings_omits_a_missing_column() -> None:
    projected = canonical_readings({"temperature_c": 91.5})

    assert projected == {"temperature": 91.5}
    assert "vibration" not in projected


def test_render_message_states_the_measurement_and_the_limit() -> None:
    """The message carries the observed value, which the replaced rules did not."""

    message = render_message(SIGNAL_SPECS["temperature"], "GT", 90.0, 95.25)

    assert message == "95.25 °C > 90 °C"


def test_render_message_uses_the_signal_unit() -> None:
    message = render_message(SIGNAL_SPECS["vibration"], "GTE", 7.0, 8.0)
    assert message == "8 mm/s >= 7 mm/s"


def valid_definition(**overrides: object) -> dict[str, object]:
    definition: dict[str, object] = {
        "rule_id": "temperature_high",
        "name": "High temperature",
        "signal_name": "temperature",
        "operator": "GT",
        "threshold": 90.0,
        "severity": "CRITICAL",
        "priority": "URGENT",
        "device_type": None,
    }
    definition.update(overrides)
    return definition


def test_a_valid_definition_reports_no_issues() -> None:
    assert validate_rule_definition(**valid_definition()) == []  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "field_path", "code"),
    [
        ({"signal_name": "torque"}, "signal_name", "SIGNAL_UNKNOWN"),
        ({"operator": "APPROX"}, "operator", "OPERATOR_UNKNOWN"),
        ({"severity": "CATASTROPHIC"}, "severity", "SEVERITY_UNKNOWN"),
        ({"priority": "WHENEVER"}, "priority", "PRIORITY_UNKNOWN"),
        ({"threshold": float("nan")}, "threshold", "THRESHOLD_NOT_FINITE"),
        ({"threshold": float("inf")}, "threshold", "THRESHOLD_NOT_FINITE"),
        ({"threshold": None}, "threshold", "THRESHOLD_NOT_FINITE"),
        ({"threshold": 500.0}, "threshold", "THRESHOLD_OUT_OF_RANGE"),
        ({"threshold": -900.0}, "threshold", "THRESHOLD_OUT_OF_RANGE"),
        ({"name": ""}, "name", "NAME_REQUIRED"),
        ({"name": "   "}, "name", "NAME_REQUIRED"),
        # The issue names the request field, which is ``id`` on the API body, even
        # though the validator argument is called ``rule_id``.
        ({"rule_id": ""}, "id", "RULE_ID_INVALID"),
        ({"rule_id": "bad id!"}, "id", "RULE_ID_INVALID"),
        ({"rule_id": "x" * 101}, "id", "RULE_ID_INVALID"),
        ({"device_type": "  "}, "device_type", "DEVICE_TYPE_INVALID"),
    ],
)
def test_an_unusable_definition_reports_its_stable_code(
    overrides: dict[str, object], field_path: str, code: str
) -> None:
    issues = validate_rule_definition(**valid_definition(**overrides))  # type: ignore[arg-type]

    assert [(issue["field"], issue["code"]) for issue in issues] == [(field_path, code)]


def test_an_out_of_range_threshold_message_names_the_permitted_range() -> None:
    issues = validate_rule_definition(**valid_definition(threshold=500.0))  # type: ignore[arg-type]

    assert "threshold" in issues[0]["field"]
    assert "-50" in issues[0]["message"]
    assert "250" in issues[0]["message"]


def test_a_disabled_rule_is_still_a_valid_definition() -> None:
    """Validity is independent of enablement, so a rule can be created disabled."""

    assert validate_rule_definition(**valid_definition()) == []  # type: ignore[arg-type]


def test_several_issues_are_reported_together() -> None:
    issues = validate_rule_definition(
        **valid_definition(signal_name="torque", operator="APPROX")  # type: ignore[arg-type]
    )

    codes = {issue["code"] for issue in issues}
    assert codes == {"SIGNAL_UNKNOWN", "OPERATOR_UNKNOWN"}
