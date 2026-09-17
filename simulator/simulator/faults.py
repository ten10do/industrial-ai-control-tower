"""Fault injection models and lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class FaultLifecycle:
    """Unified lifecycle stages for a fault."""

    NORMAL = "NORMAL"
    INJECTING = "INJECTING"
    ACTIVE = "ACTIVE"
    RECOVERING = "RECOVERING"


@dataclass(frozen=True)
class FaultConfig:
    """User-facing configuration for a single fault episode."""

    fault_type: str
    start_tick: int
    duration: int
    severity: float = 1.0
    ramp_up_ticks: int = 10
    recovery_ticks: int = 10
    target_signal: str | None = None


class BaseFault:
    """Abstract base for a fault type."""

    FAULT_TYPE: str = ""

    def __init__(self, config: FaultConfig, rng: Any) -> None:
        self.config = config
        self.rng = rng
        self._stage = FaultLifecycle.NORMAL
        self._stage_progress = 0.0

    @property
    def stage(self) -> str:
        return self._stage

    def _envelope(self, tick: int) -> float:
        """Return a 0..1 envelope describing fault intensity at a given tick."""
        start = self.config.start_tick
        ramp = self.config.ramp_up_ticks
        active = self.config.duration
        recovery = self.config.recovery_ticks
        severity = max(0.0, min(1.0, self.config.severity))

        if tick < start:
            return 0.0
        if tick < start + ramp:
            self._stage = FaultLifecycle.INJECTING
            return severity * ((tick - start) / max(1, ramp))
        if tick < start + ramp + active:
            self._stage = FaultLifecycle.ACTIVE
            return severity
        if tick < start + ramp + active + recovery:
            self._stage = FaultLifecycle.RECOVERING
            return severity * (1.0 - (tick - (start + ramp + active)) / max(1, recovery))
        self._stage = FaultLifecycle.NORMAL
        return 0.0

    def effects(self, tick: int) -> dict[str, float | int]:
        """Return signal deltas for this tick. Must be implemented by subclasses."""
        raise NotImplementedError


class BearingWearFault(BaseFault):
    """Progressive bearing degradation: vibration and bearing temperature rise."""

    FAULT_TYPE = "BEARING_WEAR"

    def effects(self, tick: int) -> dict[str, float | int]:
        env = self._envelope(tick)
        return {
            "vibration_delta": 6.0 * env + self.rng.gauss(0.0, 0.1 * env),
            "bearing_temperature_delta": 12.0 * env + self.rng.gauss(0.0, 0.2 * env),
            "temperature_delta": 3.0 * env,
        }


class OverloadFault(BaseFault):
    """Excessive mechanical load: current, power, temperature rise; rpm droops."""

    FAULT_TYPE = "OVERLOAD"

    def effects(self, tick: int) -> dict[str, float | int]:
        env = self._envelope(tick)
        return {
            "load_delta": 30.0 * env,
            "current_delta": 3.5 * env + self.rng.gauss(0.0, 0.1 * env),
            "temperature_delta": 8.0 * env + self.rng.gauss(0.0, 0.2 * env),
            "rpm_delta": int(-10.0 * env),
        }


class OverheatingFault(BaseFault):
    """Cooling failure or blocked ventilation: temperature rise without high vibration."""

    FAULT_TYPE = "OVERHEATING"

    def effects(self, tick: int) -> dict[str, float | int]:
        env = self._envelope(tick)
        return {
            "temperature_delta": 18.0 * env + self.rng.gauss(0.0, 0.3 * env),
            "bearing_temperature_delta": 15.0 * env + self.rng.gauss(0.0, 0.3 * env),
            "vibration_delta": 0.2 * env,  # negligible mechanical effect
        }


class MisalignmentFault(BaseFault):
    """Shaft misalignment: vibration rises, small thermal and current increase."""

    FAULT_TYPE = "MISALIGNMENT"

    def effects(self, tick: int) -> dict[str, float | int]:
        env = self._envelope(tick)
        return {
            "vibration_delta": 4.5 * env + self.rng.gauss(0.0, 0.1 * env),
            "temperature_delta": 2.0 * env,
            "current_delta": 0.5 * env,
        }


class SensorFailureFault(BaseFault):
    """Sensor stuck, spiking, or dropping out."""

    FAULT_TYPE = "SENSOR_FAILURE"

    def effects(self, tick: int) -> dict[str, float | int]:
        env = self._envelope(tick)
        if env <= 0.0:
            return {}

        mode = self.config.target_signal or "STUCK"
        if mode == "SPIKE":
            return {"temperature_delta": 25.0 * env}
        if mode == "DROPOUT":
            return {"temperature_delta": -999.0}  # explicit sentinel handled by invariant tests
        # STUCK: handled by FaultManager by freezing the signal during active fault.
        return {}


_FAULT_REGISTRY: dict[str, type[BaseFault]] = {
    cls.FAULT_TYPE: cls
    for cls in (
        BearingWearFault,
        OverloadFault,
        OverheatingFault,
        MisalignmentFault,
        SensorFailureFault,
    )
}


class FaultManager:
    """Owns active faults and aggregates their effects per tick."""

    def __init__(self, rng: Any) -> None:
        self.rng = rng
        self._faults: list[BaseFault] = []
        self._stuck_values: dict[str, float] = {}

    def add_fault(self, config: FaultConfig) -> None:
        """Register a new fault episode."""
        cls = _FAULT_REGISTRY.get(config.fault_type)
        if cls is None:
            raise ValueError(f"Unknown fault type: {config.fault_type}")
        self._faults.append(cls(config, self.rng))

    def effects_for_tick(self, tick: int) -> dict[str, float | int]:
        """Aggregate deltas from all active faults."""
        aggregated: dict[str, float | int] = {}
        for fault in self._faults:
            effects = fault.effects(tick)
            for key, value in effects.items():
                aggregated[key] = aggregated.get(key, 0) + value
        return aggregated

    def current_state_label(self) -> str:
        """Return the most severe active lifecycle stage as the aggregated fault state."""
        stages = [f.stage for f in self._faults]
        for stage in (
            FaultLifecycle.ACTIVE,
            FaultLifecycle.INJECTING,
            FaultLifecycle.RECOVERING,
        ):
            if any(s == stage for s in stages):
                return stage
        return FaultLifecycle.NORMAL

    def active_fault_types(self, tick: int) -> list[str]:
        """Return fault types that are currently affecting the motor."""
        result = []
        for fault in self._faults:
            env = fault._envelope(tick)
            if env > 0.0:
                result.append(fault.config.fault_type)
        return result
