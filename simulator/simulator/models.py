"""Core simulator models: telemetry schema and industrial motor."""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Telemetry(BaseModel):
    """Structured telemetry message published for each device tick."""

    schema_version: str = Field(default="1.0", description="Telemetry schema version.")
    timestamp: datetime = Field(description="UTC timestamp of the sample.")
    device_id: str = Field(description="Unique device identifier.")

    temperature_c: float = Field(description="Motor winding temperature in Celsius.")
    bearing_temperature_c: float = Field(description="Bearing temperature in Celsius.")
    vibration_mm_s: float = Field(description="Vibration velocity in mm/s RMS.")
    current_a: float = Field(description="Motor current in Amperes.")
    voltage_v: float = Field(description="Motor voltage in Volts.")
    rpm: int = Field(description="Rotational speed in revolutions per minute.")
    load_pct: float = Field(description="Load percentage relative to rated load.")
    power_kw: float = Field(description="Active power in kilowatts.")

    operating_state: str = Field(description="High-level operating state, e.g. RUNNING.")
    fault_state: str = Field(description="Aggregated fault state.")

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    def model_dump_json_mqtt(self) -> str:
        """Serialize to JSON string suitable for MQTT payload."""
        return self.model_dump_json()


class IndustrialMotor:
    """Simplified industrial motor model with correlated signals."""

    # Nominal / rated constants
    RATED_CURRENT_A = 10.0
    NOMINAL_VOLTAGE_V = 380.0
    SYNCHRONOUS_RPM = 1500
    RATED_POWER_KW = 5.5
    AMBIENT_TEMPERATURE_C = 25.0
    BASE_VIBRATION_MM_S = 1.8

    # Thermal constants
    THERMAL_GAIN_C_PER_KW = 6.0
    THERMAL_TIME_CONSTANT_TICKS = 30.0
    BEARING_OFFSET_C = 3.0
    BEARING_LAG_COEFFICIENT = 0.1

    # Correlation constants
    SLIP_RPM_PER_LOAD_PCT = 1.2
    VIBRATION_LOAD_COEFFICIENT = 0.015
    CURRENT_NOISE_A = 0.08
    VOLTAGE_NOISE_V = 1.5
    RPM_NOISE = 3
    LOAD_NOISE_PCT = 0.3
    TEMPERATURE_NOISE_C = 0.05
    BEARING_TEMP_NOISE_C = 0.05
    VIBRATION_NOISE_MM_S = 0.03

    def __init__(
        self,
        device_id: str = "MOTOR-001",
        seed: int | None = None,
        initial_load_pct: float = 50.0,
    ) -> None:
        self.device_id = device_id
        self.rng = random.Random(seed)

        # Operating state
        self.operating_state = "RUNNING"
        self.fault_state = "NORMAL"

        # Continuous state variables
        self.load_pct = float(initial_load_pct)
        self.voltage_v = self.NOMINAL_VOLTAGE_V
        self.current_a = self._current_from_load(self.load_pct)
        self.rpm = self._rpm_from_load(self.load_pct)
        self.power_kw = self._power_from_current_voltage(self.current_a, self.voltage_v)

        # Thermal state
        self.temperature_c = self._steady_state_temperature(self.power_kw)
        self.bearing_temperature_c = self.temperature_c + self.BEARING_OFFSET_C

        # Vibration state
        self.vibration_mm_s = self._vibration_from_load(self.load_pct)

    def _current_from_load(self, load_pct: float) -> float:
        """Current scales roughly with load percentage."""
        return (load_pct / 100.0) * self.RATED_CURRENT_A + self.rng.gauss(0.0, self.CURRENT_NOISE_A)

    def _rpm_from_load(self, load_pct: float) -> int:
        """RPM decreases slightly as load increases due to slip."""
        slip = load_pct * self.SLIP_RPM_PER_LOAD_PCT
        noise = int(round(self.rng.gauss(0.0, self.RPM_NOISE)))
        rpm = self.SYNCHRONOUS_RPM - int(round(slip)) + noise
        return max(0, rpm)

    def _power_from_current_voltage(self, current_a: float, voltage_v: float) -> float:
        """Approximate three-phase active power assuming constant power factor."""
        power_factor = 0.88
        sqrt3 = math.sqrt(3)
        return (sqrt3 * voltage_v * current_a * power_factor) / 1000.0

    def _vibration_from_load(self, load_pct: float) -> float:
        """Base vibration increases mildly with load."""
        base = self.BASE_VIBRATION_MM_S + load_pct * self.VIBRATION_LOAD_COEFFICIENT
        return max(0.0, base + self.rng.gauss(0.0, self.VIBRATION_NOISE_MM_S))

    def _steady_state_temperature(self, power_kw: float) -> float:
        """Steady-state winding temperature for a given power output."""
        return self.AMBIENT_TEMPERATURE_C + self.THERMAL_GAIN_C_PER_KW * power_kw

    def _update_load(self) -> None:
        """Load wanders slowly around its current value to simulate process variation."""
        drift = self.rng.gauss(0.0, self.LOAD_NOISE_PCT)
        self.load_pct = max(10.0, min(110.0, self.load_pct + drift))

    def _update_electrical(self) -> None:
        """Update current, voltage, rpm, and power based on load."""
        voltage_noise = self.rng.gauss(0.0, self.VOLTAGE_NOISE_V)
        self.voltage_v = max(0.0, self.NOMINAL_VOLTAGE_V + voltage_noise)
        self.current_a = max(0.0, self._current_from_load(self.load_pct))
        self.rpm = self._rpm_from_load(self.load_pct)
        self.power_kw = max(0.0, self._power_from_current_voltage(self.current_a, self.voltage_v))

    def _update_thermal(self) -> None:
        """First-order thermal response toward steady state."""
        target = self._steady_state_temperature(self.power_kw)
        alpha = 1.0 - math.exp(-1.0 / self.THERMAL_TIME_CONSTANT_TICKS)
        self.temperature_c = (
            self.temperature_c
            + alpha * (target - self.temperature_c)
            + self.rng.gauss(0.0, self.TEMPERATURE_NOISE_C)
        )

        # Bearing temperature lags winding temperature and carries bearing-specific heat.
        target_bearing = self.temperature_c + self.BEARING_OFFSET_C
        self.bearing_temperature_c = (
            self.bearing_temperature_c
            + self.BEARING_LAG_COEFFICIENT * (target_bearing - self.bearing_temperature_c)
            + self.rng.gauss(0.0, self.BEARING_TEMP_NOISE_C)
        )

    def _update_vibration(self) -> None:
        """Base mechanical vibration from load."""
        target = self._vibration_from_load(self.load_pct)
        # Vibration responds quickly; use strong pull toward target.
        self.vibration_mm_s = 0.8 * self.vibration_mm_s + 0.2 * target
        self.vibration_mm_s = max(0.0, self.vibration_mm_s)

    def step(
        self,
        fault_effects: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> Telemetry:
        """Advance the motor by one simulation tick and return telemetry."""
        fault_effects = fault_effects or {}

        self._update_load()
        self._update_electrical()
        self._update_thermal()
        self._update_vibration()

        # Apply fault effects if present.
        self.vibration_mm_s += fault_effects.get("vibration_delta", 0.0)
        self.temperature_c += fault_effects.get("temperature_delta", 0.0)
        self.bearing_temperature_c += fault_effects.get("bearing_temperature_delta", 0.0)
        self.current_a += fault_effects.get("current_delta", 0.0)
        self.load_pct = max(0.0, min(120.0, self.load_pct + fault_effects.get("load_delta", 0.0)))
        self.rpm = max(0, self.rpm + fault_effects.get("rpm_delta", 0))
        self.power_kw = max(0.0, self._power_from_current_voltage(self.current_a, self.voltage_v))

        return Telemetry(
            timestamp=timestamp if timestamp is not None else _utc_now(),
            device_id=self.device_id,
            temperature_c=round(self.temperature_c, 2),
            bearing_temperature_c=round(self.bearing_temperature_c, 2),
            vibration_mm_s=round(self.vibration_mm_s, 2),
            current_a=round(self.current_a, 2),
            voltage_v=round(self.voltage_v, 1),
            rpm=self.rpm,
            load_pct=round(self.load_pct, 1),
            power_kw=round(self.power_kw, 2),
            operating_state=self.operating_state,
            fault_state=self.fault_state,
        )

    def set_fault_state(self, state: str) -> None:
        """Set the aggregated fault state label."""
        self.fault_state = state
