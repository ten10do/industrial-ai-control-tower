"""Run a deterministic demo and print a concise trend summary."""

from __future__ import annotations

from datetime import UTC, datetime

from simulator.engine import SimulationClock, SimulationEngine
from simulator.faults import FaultConfig, FaultManager
from simulator.models import IndustrialMotor
from simulator.publishers import InMemoryPublisher


def run_demo() -> None:
    motor = IndustrialMotor(device_id="MOTOR-001", seed=42)
    clock = SimulationClock(
        start_time=datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC),
        tick_duration=1.0,
        realtime=False,
    )
    manager = FaultManager(motor.rng)
    manager.add_fault(
        FaultConfig(
            fault_type="BEARING_WEAR",
            start_tick=30,
            duration=90,
            severity=1.0,
            ramp_up_ticks=15,
            recovery_ticks=15,
        )
    )
    publisher = InMemoryPublisher()
    engine = SimulationEngine(motor=motor, clock=clock, fault_manager=manager)
    engine.add_handler(publisher.publish)

    engine.run(max_ticks=150)

    print("Tick | Vibration | BearingTemp | WindingTemp | FaultState")
    print("-" * 60)
    for tick in [0, 29, 45, 75, 105, 120, 149]:
        t = publisher.messages[tick]
        print(
            f"{tick:4} | {t.vibration_mm_s:9.2f} | "
            f"{t.bearing_temperature_c:11.2f} | {t.temperature_c:11.2f} | {t.fault_state}"
        )


if __name__ == "__main__":
    run_demo()
