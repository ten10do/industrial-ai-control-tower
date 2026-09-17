"""Command-line interface for the simulator."""

from __future__ import annotations

import argparse
import signal
import sys
from types import FrameType

from simulator.config import SimulatorConfig
from simulator.engine import SimulationClock, SimulationEngine
from simulator.faults import FaultConfig, FaultManager
from simulator.logging_config import configure_logging
from simulator.models import IndustrialMotor
from simulator.publishers import InMemoryPublisher, MqttPublisher, TelemetryPublisher


class _Runtime:
    """Holds runtime objects so signal handlers can shut down cleanly."""

    def __init__(self) -> None:
        self.engine: SimulationEngine | None = None
        self.publisher: TelemetryPublisher | None = None

    def shutdown(self, signum: int, frame: FrameType | None) -> None:
        print("\nShutdown requested...", file=sys.stderr)
        if self.engine is not None:
            self.engine.stop()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Industrial AI Control Tower — Equipment Simulator"
    )
    parser.add_argument("--device-id", default=None, help="Device identifier")
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    parser.add_argument("--sample-interval", type=float, default=None, help="Seconds per tick")
    parser.add_argument("--max-ticks", type=int, default=None, help="Maximum ticks")
    parser.add_argument("--realtime", action="store_true", default=None, help="Wait wall-clock")
    parser.add_argument("--no-realtime", action="store_true", default=False, help="Run fast")
    parser.add_argument("--mqtt-broker-host", default=None, help="MQTT broker host")
    parser.add_argument("--mqtt-broker-port", type=int, default=None, help="MQTT broker port")
    parser.add_argument("--mqtt-topic-prefix", default=None, help="MQTT topic prefix")
    parser.add_argument("--fault-type", default=None, help="Fault type to inject")
    parser.add_argument("--fault-start-tick", type=int, default=None, help="Fault start tick")
    parser.add_argument("--fault-duration", type=int, default=None, help="Fault active ticks")
    parser.add_argument("--fault-severity", type=float, default=None, help="Fault severity 0..1")
    parser.add_argument("--no-mqtt", action="store_true", default=False, help="Disable MQTT")
    parser.add_argument("--log-level", default=None, help="Logging level")
    return parser


def _override_config_from_args(
    config: SimulatorConfig, args: argparse.Namespace
) -> SimulatorConfig:
    """Apply CLI overrides on top of environment/defaults."""
    values = config.model_dump()
    for key, value in vars(args).items():
        if value is not None:
            if key == "no_realtime" and value:
                values["realtime"] = False
            elif key != "no_realtime":
                values[key] = value
    return SimulatorConfig(**values)


def _create_publisher(config: SimulatorConfig, no_mqtt: bool) -> TelemetryPublisher:
    if no_mqtt:
        return InMemoryPublisher()
    return MqttPublisher(
        broker_host=config.mqtt_broker_host,
        broker_port=config.mqtt_broker_port,
        topic_prefix=config.mqtt_topic_prefix,
        client_id=f"simulator-{config.device_id}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    config = SimulatorConfig()
    config = _override_config_from_args(config, args)
    configure_logging(config.log_level)

    motor = IndustrialMotor(
        device_id=config.device_id,
        seed=config.seed,
    )
    clock = SimulationClock(
        tick_duration=config.sample_interval,
        realtime=config.realtime,
    )

    fault_manager: FaultManager | None = None
    if config.fault_type:
        fault_manager = FaultManager(motor.rng)
        fault_manager.add_fault(
            FaultConfig(
                fault_type=config.fault_type,
                start_tick=config.fault_start_tick,
                duration=config.fault_duration,
                severity=config.fault_severity,
            )
        )

    publisher = _create_publisher(config, no_mqtt=args.no_mqtt)
    engine = SimulationEngine(motor=motor, clock=clock, fault_manager=fault_manager)
    engine.add_handler(lambda t: print(t.model_dump_json()))
    engine.add_handler(publisher.publish)

    runtime = _Runtime()
    runtime.engine = engine
    runtime.publisher = publisher
    signal.signal(signal.SIGINT, runtime.shutdown)
    signal.signal(signal.SIGTERM, runtime.shutdown)

    try:
        with publisher:
            publisher.publish_status(config.device_id, "online")
            engine.run(max_ticks=config.max_ticks)
            publisher.publish_status(config.device_id, "offline")
    except Exception as exc:
        print(f"Simulator failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
