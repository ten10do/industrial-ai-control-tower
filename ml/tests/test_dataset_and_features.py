"""Mandatory determinism, split-isolation, and leakage tests."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from app.ml.features import (
    FORBIDDEN_FEATURE_FIELDS,
    FeatureExtractor,
    FeatureValidationError,
    TelemetryWindow,
    WindowSample,
)

from industrial_ml.dataset import CLASSES, build_scenarios, generate_dataset


def sample(index: int, *, temperature: float = 50.0) -> WindowSample:
    return WindowSample(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
        temperature_c=temperature,
        bearing_temperature_c=53.0,
        vibration_mm_s=2.0,
        current_a=5.0,
        voltage_v=380.0,
        rpm=1440,
        load_pct=50.0,
        power_kw=3.0,
    )


def test_generation_is_deterministic() -> None:
    counts = dict.fromkeys(CLASSES, 2)
    scenarios = build_scenarios(counts, ticks=60)
    first = generate_dataset(scenarios)
    second = generate_dataset(scenarios)
    np.testing.assert_array_equal(first.X, second.X)
    np.testing.assert_array_equal(first.y, second.y)


def test_scenario_and_seed_groups_do_not_overlap_splits() -> None:
    scenarios = build_scenarios(dict.fromkeys(CLASSES, 5), ticks=60)
    for left, right in (("train", "validation"), ("train", "test"), ("validation", "test")):
        left_scenarios = {item.scenario_id for item in scenarios if item.split == left}
        right_scenarios = {item.scenario_id for item in scenarios if item.split == right}
        left_seeds = {item.seed for item in scenarios if item.split == left}
        right_seeds = {item.seed for item in scenarios if item.split == right}
        assert left_scenarios.isdisjoint(right_scenarios)
        assert left_seeds.isdisjoint(right_seeds)


def test_every_class_has_train_validation_and_test_scenarios() -> None:
    scenarios = build_scenarios(dict.fromkeys(CLASSES, 5), ticks=60)
    observed = {(item.fault_type, item.split) for item in scenarios}
    expected = {(label, split) for label in CLASSES for split in ("train", "validation", "test")}
    assert observed == expected


def test_forbidden_labels_cannot_enter_feature_schema() -> None:
    extractor = FeatureExtractor()
    extractor.validate_schema()
    assert not set(extractor.feature_names).intersection(FORBIDDEN_FEATURE_FIELDS)
    assert all("fault" not in name and "severity" not in name for name in extractor.feature_names)

    base = sample(0).model_dump()
    first = WindowSample.model_validate(
        {**base, "fault_state": "NORMAL", "fault_type": "NORMAL", "severity": 0.0}
    )
    second = WindowSample.model_validate(
        {
            **base,
            "fault_state": "ACTIVE",
            "fault_type": "BEARING_WEAR",
            "severity": 1.0,
        }
    )
    assert first == second
    assert not set(WindowSample.model_fields).intersection(FORBIDDEN_FEATURE_FIELDS)


def test_feature_vector_is_deterministic_and_finite() -> None:
    extractor = FeatureExtractor(window_size=20)
    window = TelemetryWindow(device_id="MOTOR-001", samples=[sample(i) for i in range(20)])
    first = extractor.extract(window)
    second = extractor.extract(window)
    np.testing.assert_array_equal(first, second)
    assert len(first) == 76
    assert np.all(np.isfinite(first))


def test_missing_nan_and_insufficient_windows_are_rejected() -> None:
    extractor = FeatureExtractor(window_size=20)
    with pytest.raises(FeatureValidationError, match="insufficient"):
        extractor.extract(
            TelemetryWindow(device_id="MOTOR-001", samples=[sample(i) for i in range(10)])
        )
    missing = [sample(i) for i in range(19)] + [sample(30)]
    with pytest.raises(FeatureValidationError, match="missing"):
        extractor.extract(TelemetryWindow(device_id="MOTOR-001", samples=missing))
    invalid = [sample(i) for i in range(20)]
    invalid[-1].temperature_c = float("nan")
    with pytest.raises(FeatureValidationError, match="NaN"):
        extractor.extract(TelemetryWindow(device_id="MOTOR-001", samples=invalid))
