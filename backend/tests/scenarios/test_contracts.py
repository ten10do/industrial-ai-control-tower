"""Strict scenario-definition and suite-loading tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.scenarios.contracts import ScenarioDefinition
from app.scenarios.loader import load_suite


def valid_definition() -> dict[str, object]:
    return {
        "scenario_id": "bearing_case",
        "description": "bearing wear validation",
        "kind": "SINGLE_FAULT",
        "device": {"device_id": "MOTOR-001"},
        "fault": {"type": "BEARING_WEAR"},
        "execution": {"warmup_seconds": 20, "fault_duration_seconds": 20},
        "expected": {
            "alarm": {"required": True},
            "incident": {"required": True},
            "diagnosis": {"expected_fault": "BEARING_WEAR"},
            "evidence": {},
            "workflow": {},
            "safety": {},
            "workorder": {},
        },
    }


def test_unknown_field_is_a_hard_failure() -> None:
    value = valid_definition()
    value["typo"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ScenarioDefinition.model_validate(value)


def test_unknown_fault_is_a_hard_failure() -> None:
    value = valid_definition()
    value["fault"] = {"type": "IMAGINARY_FAULT"}
    with pytest.raises(ValidationError):
        ScenarioDefinition.model_validate(value)


def test_invalid_timing_is_a_hard_failure() -> None:
    value = valid_definition()
    value["execution"] = {"fault_duration_seconds": 0}
    with pytest.raises(ValidationError, match="must be positive"):
        ScenarioDefinition.model_validate(value)


def test_frozen_v1_suite_loads_and_contains_required_cases() -> None:
    root = Path(__file__).parents[3] / "scenarios" / "v1"
    scenarios = load_suite(root)
    ids = {item.scenario_id for item in scenarios}
    assert len(scenarios) == 17
    assert {
        "normal_baseline",
        "bearing_wear_progressive",
        "overheating_single_fault",
        "overload_single_fault",
        "misalignment_progressive",
        "sensor_failure_spike",
        "bearing_wear_recovery",
        "bearing_wear_duplicate_input",
        "bearing_wear_out_of_order_input",
    } <= ids
