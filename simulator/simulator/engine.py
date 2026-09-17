"""Simulation clock and engine."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from simulator.models import IndustrialMotor, Telemetry


@dataclass
class SimulationClock:
    """Decouples simulation time from wall clock.

    The clock advances by ``tick_duration`` seconds for each tick. When
    ``realtime`` is False, the engine does not sleep between ticks, allowing
    tests to run as fast as the CPU allows.
    """

    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    tick_duration: float = 1.0
    realtime: bool = True
    _tick: int = field(default=0, init=False)

    def current_time(self) -> datetime:
        """Return the current simulation timestamp."""
        return self.start_time.fromtimestamp(
            self.start_time.timestamp() + self._tick * self.tick_duration,
            tz=UTC,
        )

    def advance(self) -> None:
        """Advance one tick and optionally sleep to match wall time."""
        if self.realtime and self._tick > 0:
            time.sleep(self.tick_duration)
        self._tick += 1

    @property
    def tick(self) -> int:
        return self._tick


TelemetryHandler = Callable[[Telemetry], None]


class SimulationEngine:
    """Orchestrates the motor model, fault injection, clock, and publishers."""

    def __init__(
        self,
        motor: IndustrialMotor,
        clock: SimulationClock,
        fault_manager: Any | None = None,
        handlers: list[TelemetryHandler] | None = None,
    ) -> None:
        self.motor = motor
        self.clock = clock
        self.fault_manager = fault_manager
        self.handlers = handlers or []
        self._running = False

    def add_handler(self, handler: TelemetryHandler) -> None:
        """Register a telemetry consumer."""
        self.handlers.append(handler)

    def run(self, max_ticks: int | None = None) -> None:
        """Run the simulation loop until max_ticks or stop() is called."""
        self._running = True
        tick_count = 0
        try:
            while self._running:
                if max_ticks is not None and tick_count >= max_ticks:
                    break

                fault_effects = {}
                if self.fault_manager is not None:
                    fault_effects = self.fault_manager.effects_for_tick(self.clock.tick)
                    self.motor.set_fault_state(self.fault_manager.current_state_label())

                telemetry = self.motor.step(fault_effects)
                # Override wall-clock timestamp with simulation clock for determinism.
                telemetry = telemetry.model_copy(update={"timestamp": self.clock.current_time()})

                for handler in self.handlers:
                    handler(telemetry)

                self.clock.advance()
                tick_count += 1
        finally:
            self._running = False

    def stop(self) -> None:
        """Request graceful shutdown of the simulation loop."""
        self._running = False
