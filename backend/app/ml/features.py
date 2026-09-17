"""Deterministic, leakage-safe telemetry window feature pipeline."""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FEATURE_VERSION = "features-v1"
SIGNALS = (
    "temperature_c",
    "bearing_temperature_c",
    "vibration_mm_s",
    "current_a",
    "voltage_v",
    "rpm",
    "load_pct",
    "power_kw",
)
STATISTICS = ("mean", "std", "min", "max", "median", "slope", "delta", "range", "variance")
FORBIDDEN_FEATURE_FIELDS = frozenset(
    {"fault_state", "fault_type", "severity", "scenario_id", "scenario_label"}
)
SIGNAL_RANGES = {
    "temperature_c": (-50.0, 250.0),
    "bearing_temperature_c": (-50.0, 250.0),
    "vibration_mm_s": (0.0, 200.0),
    "current_a": (0.0, 10_000.0),
    "voltage_v": (0.0, 10_000.0),
    "rpm": (0.0, 100_000.0),
    "load_pct": (0.0, 120.0),
    "power_kw": (0.0, 100_000.0),
}


class FeatureValidationError(ValueError):
    """A telemetry window cannot safely be converted into features."""


class WindowSample(BaseModel):
    """Only serving signals enter the feature boundary; labels cannot be represented here."""

    model_config = ConfigDict(extra="ignore")

    timestamp: datetime
    temperature_c: float
    bearing_temperature_c: float
    vibration_mm_s: float
    current_a: float
    voltage_v: float
    rpm: int
    load_pct: float
    power_kw: float

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class TelemetryWindow(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    device_id: str
    samples: list[WindowSample] = Field(min_length=2)

    @model_validator(mode="after")
    def ordered(self) -> TelemetryWindow:
        timestamps = [sample.timestamp for sample in self.samples]
        if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
            raise ValueError("window timestamps must be strictly increasing")
        return self

    @property
    def start(self) -> datetime:
        return self.samples[0].timestamp

    @property
    def end(self) -> datetime:
        return self.samples[-1].timestamp


class FeatureExtractor:
    """Extract 76 bounded statistics and cross-signal features from one window."""

    def __init__(self, window_size: int = 20, max_gap_factor: float = 2.0) -> None:
        if window_size < 2:
            raise ValueError("window_size must be at least 2")
        self.window_size = window_size
        self.max_gap_factor = max_gap_factor

    @property
    def feature_names(self) -> tuple[str, ...]:
        names = [f"{signal}__{stat}" for signal in SIGNALS for stat in STATISTICS]
        names.extend(
            (
                "current_per_load__mean",
                "power_per_load__mean",
                "bearing_motor_delta__mean",
                "rpm_deviation__mean",
            )
        )
        return tuple(names)

    def extract(self, window: TelemetryWindow) -> NDArray[np.float64]:
        if len(window.samples) != self.window_size:
            raise FeatureValidationError(
                f"insufficient window: expected {self.window_size}, got {len(window.samples)}"
            )
        intervals = np.diff([sample.timestamp.timestamp() for sample in window.samples])
        typical = float(np.median(intervals))
        if typical <= 0 or float(np.max(intervals)) > typical * self.max_gap_factor:
            raise FeatureValidationError("missing or irregular telemetry sample detected")

        arrays: dict[str, NDArray[np.float64]] = {}
        for signal in SIGNALS:
            values = np.asarray([getattr(sample, signal) for sample in window.samples], dtype=float)
            lower, upper = SIGNAL_RANGES[signal]
            if not np.all(np.isfinite(values)):
                raise FeatureValidationError(f"{signal} contains NaN or infinity")
            if np.any(values < lower) or np.any(values > upper):
                raise FeatureValidationError(f"{signal} contains an out-of-range value")
            arrays[signal] = values

        features: list[float] = []
        x = np.arange(self.window_size, dtype=float)
        x_centered = x - x.mean()
        denominator = float(np.dot(x_centered, x_centered))
        for signal in SIGNALS:
            values = arrays[signal]
            slope = float(np.dot(x_centered, values - values.mean()) / denominator)
            features.extend(
                (
                    float(values.mean()),
                    float(values.std()),
                    float(values.min()),
                    float(values.max()),
                    float(np.median(values)),
                    slope,
                    float(values[-1] - values[0]),
                    float(np.ptp(values)),
                    float(values.var()),
                )
            )

        load = np.maximum(arrays["load_pct"], 1.0)
        features.extend(
            (
                float(np.mean(arrays["current_a"] / load)),
                float(np.mean(arrays["power_kw"] / load)),
                float(np.mean(arrays["bearing_temperature_c"] - arrays["temperature_c"])),
                float(np.mean(np.abs(arrays["rpm"] - 1500.0))),
            )
        )
        result = np.asarray(features, dtype=float)
        if not np.all(np.isfinite(result)):
            raise FeatureValidationError("feature vector contains NaN or infinity")
        return result

    def validate_schema(self) -> None:
        names = set(self.feature_names)
        leaked = names.intersection(FORBIDDEN_FEATURE_FIELDS)
        if leaked:
            raise RuntimeError(f"forbidden label fields in feature schema: {sorted(leaked)}")
        if len(names) != len(self.feature_names):
            raise RuntimeError("feature names must be unique")


def sigmoid(value: float) -> float:
    """Numerically stable scalar sigmoid."""
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)
