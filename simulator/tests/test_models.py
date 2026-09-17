"""Tests for the IndustrialMotor model and Telemetry schema."""

import math
from datetime import UTC

import pytest

from simulator.models import IndustrialMotor, Telemetry


class TestTelemetrySchema:
    """Telemetry validation and serialization."""

    def test_timestamp_must_be_timezone_aware(self) -> None:
        from datetime import datetime

        with pytest.raises(ValueError):
            Telemetry(
                timestamp=datetime(2026, 1, 1, 12, 0, 0),
                device_id="MOTOR-001",
                temperature_c=50.0,
                bearing_temperature_c=55.0,
                vibration_mm_s=2.0,
                current_a=5.0,
                voltage_v=380.0,
                rpm=1500,
                load_pct=50.0,
                power_kw=3.0,
                operating_state="RUNNING",
                fault_state="NORMAL",
            )

    def test_json_serialization(self) -> None:
        motor = IndustrialMotor(seed=42)
        t = motor.step()
        raw = t.model_dump_json()
        assert '"device_id":"MOTOR-001"' in raw
        assert '"schema_version":"1.0"' in raw


class TestIndustrialMotor:
    """Motor behavior and signal relationships."""

    def test_determinism(self) -> None:
        from datetime import datetime

        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        motor_a = IndustrialMotor(seed=123)
        motor_b = IndustrialMotor(seed=123)

        samples_a = [motor_a.step(timestamp=base_time) for _ in range(20)]
        samples_b = [motor_b.step(timestamp=base_time) for _ in range(20)]

        for a, b in zip(samples_a, samples_b, strict=True):
            assert a.model_dump() == b.model_dump()

    def test_temporal_continuity(self) -> None:
        motor = IndustrialMotor(seed=1)
        temps = [motor.step().temperature_c for _ in range(50)]
        max_jump = max(abs(temps[i] - temps[i - 1]) for i in range(1, len(temps)))
        assert max_jump < 2.0, f"Temperature jumped {max_jump} C between ticks"

    def test_load_current_power_correlation(self) -> None:
        motor = IndustrialMotor(seed=7, initial_load_pct=80.0)
        # Burn-in to reach steady state.
        for _ in range(30):
            motor.step()

        sample = motor.step()
        assert 0 <= sample.load_pct <= 110
        assert sample.current_a > 0
        assert sample.power_kw > 0
        # Higher load should produce higher current and power than a low-load motor.
        low_load_motor = IndustrialMotor(seed=8, initial_load_pct=20.0)
        for _ in range(30):
            low_load_motor.step()
        low = low_load_motor.step()
        assert sample.current_a > low.current_a
        assert sample.power_kw > low.power_kw

    def test_rpm_decreases_with_load(self) -> None:
        light = IndustrialMotor(seed=9, initial_load_pct=20.0)
        heavy = IndustrialMotor(seed=10, initial_load_pct=90.0)
        for _ in range(30):
            light.step()
            heavy.step()
        assert heavy.step().rpm < light.step().rpm

    def test_invariants(self) -> None:
        motor = IndustrialMotor(seed=11)
        for _ in range(100):
            t = motor.step()
            assert 0 <= t.load_pct <= 120
            assert t.voltage_v >= 0
            assert t.rpm >= 0
            assert t.current_a >= 0
            assert t.power_kw >= 0
            assert not math.isnan(t.temperature_c)
            assert not math.isinf(t.vibration_mm_s)
            assert t.bearing_temperature_c >= t.temperature_c - 5.0
