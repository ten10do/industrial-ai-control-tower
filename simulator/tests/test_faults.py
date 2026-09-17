"""Tests for fault injection behavior and lifecycle."""

from __future__ import annotations

import random
from typing import Any

import pytest

from simulator.faults import BearingWearFault, FaultConfig, FaultLifecycle, FaultManager
from simulator.models import IndustrialMotor, Telemetry


class TestFaultLifecycle:
    """Fault envelope and lifecycle transitions."""

    def test_lifecycle_normal_to_active_to_recovery(self) -> None:
        fault = BearingWearFault(
            FaultConfig(
                fault_type="BEARING_WEAR",
                start_tick=10,
                duration=20,
                ramp_up_ticks=5,
                recovery_ticks=5,
            ),
            random.Random(1),
        )

        assert fault._envelope(5) == 0.0
        assert fault.stage == FaultLifecycle.NORMAL

        injecting = fault._envelope(12)
        assert 0 < injecting < 1.0
        assert fault.stage == FaultLifecycle.INJECTING

        active = fault._envelope(20)
        assert active > 0.95
        assert fault.stage == FaultLifecycle.ACTIVE

        recovering = fault._envelope(37)
        assert 0 < recovering < active
        assert fault.stage == FaultLifecycle.RECOVERING

        assert fault._envelope(50) == 0.0
        assert fault.stage == FaultLifecycle.NORMAL


class TestFaultPatterns:
    """Each fault must produce a distinguishable signal pattern."""

    @staticmethod
    def _baseline_and_faulted(fault_type: str, **kwargs: Any) -> tuple[Telemetry, Telemetry]:
        motor_baseline = IndustrialMotor(seed=100)
        for _ in range(40):
            motor_baseline.step()
        baseline = motor_baseline.step()

        motor_fault = IndustrialMotor(seed=100)
        manager = FaultManager(motor_fault.rng)
        manager.add_fault(
            FaultConfig(
                fault_type=fault_type,
                start_tick=10,
                duration=20,
                severity=1.0,
                **kwargs,
            )
        )
        samples = []
        for tick in range(41):
            effects = manager.effects_for_tick(tick)
            motor_fault.set_fault_state(manager.current_state_label())
            samples.append(motor_fault.step(effects))
        faulted = samples[-1]
        return baseline, faulted

    def test_bearing_wear_raises_vibration_and_bearing_temp(self) -> None:
        baseline, faulted = self._baseline_and_faulted("BEARING_WEAR")
        assert faulted.vibration_mm_s > baseline.vibration_mm_s + 2.0
        assert faulted.bearing_temperature_c > baseline.bearing_temperature_c + 2.0

    def test_overload_raises_load_current_power_and_temperature(self) -> None:
        baseline, faulted = self._baseline_and_faulted("OVERLOAD")
        assert faulted.load_pct > baseline.load_pct + 15.0
        assert faulted.current_a > baseline.current_a + 1.0
        assert faulted.power_kw > baseline.power_kw + 0.5
        assert faulted.temperature_c > baseline.temperature_c + 1.0
        assert faulted.rpm <= baseline.rpm

    def test_overheating_raises_temperature_without_high_vibration(self) -> None:
        baseline, faulted = self._baseline_and_faulted("OVERHEATING")
        assert faulted.temperature_c > baseline.temperature_c + 5.0
        assert faulted.bearing_temperature_c > baseline.bearing_temperature_c + 3.0
        assert faulted.vibration_mm_s < baseline.vibration_mm_s + 1.5

    def test_misalignment_raises_vibration_with_mild_thermal(self) -> None:
        baseline, faulted = self._baseline_and_faulted("MISALIGNMENT")
        assert faulted.vibration_mm_s > baseline.vibration_mm_s + 1.5
        assert faulted.temperature_c > baseline.temperature_c + 0.5

    def test_sensor_failure_spike(self) -> None:
        baseline, faulted = self._baseline_and_faulted("SENSOR_FAILURE", target_signal="SPIKE")
        assert faulted.temperature_c > baseline.temperature_c + 15.0


class TestFaultManager:
    """Aggregation of multiple faults."""

    def test_aggregates_effects(self) -> None:
        motor = IndustrialMotor(seed=200)
        manager = FaultManager(motor.rng)
        manager.add_fault(FaultConfig(fault_type="BEARING_WEAR", start_tick=5, duration=10))
        manager.add_fault(FaultConfig(fault_type="OVERLOAD", start_tick=5, duration=10))
        effects = manager.effects_for_tick(10)
        assert "vibration_delta" in effects
        assert "load_delta" in effects

    def test_unknown_fault_type_raises(self) -> None:
        manager = FaultManager(None)
        with pytest.raises(ValueError):
            manager.add_fault(FaultConfig(fault_type="UNKNOWN", start_tick=0, duration=1))

    def test_active_fault_types(self) -> None:
        manager = FaultManager(None)
        manager.add_fault(FaultConfig(fault_type="OVERHEATING", start_tick=5, duration=5))
        assert manager.active_fault_types(7) == ["OVERHEATING"]
        assert manager.active_fault_types(1) == []
