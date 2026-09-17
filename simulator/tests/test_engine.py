"""Tests for the simulation engine and clock."""

from datetime import UTC, datetime

from simulator.engine import SimulationClock, SimulationEngine
from simulator.faults import FaultConfig, FaultLifecycle, FaultManager
from simulator.models import IndustrialMotor
from simulator.publishers import InMemoryPublisher


class TestSimulationClock:
    """Clock decouples simulation time from wall time."""

    def test_clock_advances_without_sleeping_when_not_realtime(self) -> None:
        start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        clock = SimulationClock(start_time=start, tick_duration=2.0, realtime=False)

        assert clock.current_time() == start
        clock.advance()
        assert clock.current_time() == datetime(2026, 1, 1, 12, 0, 2, tzinfo=UTC)
        clock.advance()
        assert clock.current_time() == datetime(2026, 1, 1, 12, 0, 4, tzinfo=UTC)


class TestSimulationEngine:
    """Engine orchestration."""

    def test_engine_calls_handlers(self) -> None:
        motor = IndustrialMotor(seed=1)
        clock = SimulationClock(realtime=False)
        publisher = InMemoryPublisher()
        engine = SimulationEngine(motor=motor, clock=clock)
        engine.add_handler(publisher.publish)

        engine.run(max_ticks=10)

        assert len(publisher.messages) == 10
        assert publisher.messages[0].device_id == "MOTOR-001"
        assert all(m.timestamp.tzinfo is not None for m in publisher.messages)

    def test_engine_uses_simulation_clock_timestamp(self) -> None:
        start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        motor = IndustrialMotor(seed=2)
        clock = SimulationClock(start_time=start, tick_duration=1.0, realtime=False)
        publisher = InMemoryPublisher()
        engine = SimulationEngine(motor=motor, clock=clock)
        engine.add_handler(publisher.publish)

        engine.run(max_ticks=3)

        assert publisher.messages[0].timestamp == start
        assert publisher.messages[1].timestamp == datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC)

    def test_engine_with_fault_manager(self) -> None:
        motor = IndustrialMotor(seed=3)
        clock = SimulationClock(realtime=False)
        manager = FaultManager(motor.rng)
        manager.add_fault(
            FaultConfig(
                fault_type="BEARING_WEAR",
                start_tick=2,
                duration=5,
                ramp_up_ticks=3,
                recovery_ticks=3,
            )
        )
        publisher = InMemoryPublisher()
        engine = SimulationEngine(motor=motor, clock=clock, fault_manager=manager)
        engine.add_handler(publisher.publish)

        engine.run(max_ticks=20)

        states = [m.fault_state for m in publisher.messages]
        assert FaultLifecycle.ACTIVE in states
        assert states[-1] == "NORMAL"

    def test_graceful_stop(self) -> None:
        motor = IndustrialMotor(seed=4)
        clock = SimulationClock(realtime=False)
        publisher = InMemoryPublisher()
        engine = SimulationEngine(motor=motor, clock=clock)
        engine.add_handler(publisher.publish)

        engine.run(max_ticks=100)
        assert len(publisher.messages) == 100
