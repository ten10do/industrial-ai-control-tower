# Simulator

## Overview

The `simulator/` package produces synthetic telemetry for an `IndustrialMotor` and publishes it over MQTT. It is an engineering simulation intended for development, testing, and demonstration, not a validated digital twin of any specific physical motor.

## Model Assumptions

- One device type is modeled: `IndustrialMotor`.
- Default device identifier: `MOTOR-001`.
- Sampling defaults to one sample per second; this is decoupled from wall clock via `SimulationClock`.
- Signals are correlated rather than independently random:
  - `load_pct` drives `current_a` and `power_kw`.
  - Higher load increases slip, so `rpm` decreases slightly.
  - `power_kw` and thermal losses drive `temperature_c`.
  - `bearing_temperature_c` tracks winding temperature with a small offset and lag.
  - `vibration_mm_s` has a base level plus a mild load contribution.
- A random seed makes the sequence reproducible.

## Telemetry Fields

| Field | Unit | Description |
|-------|------|-------------|
| `schema_version` | string | Currently `1.0` |
| `timestamp` | ISO 8601 UTC | Sample timestamp |
| `device_id` | string | Unique device identifier |
| `temperature_c` | °C | Motor winding temperature |
| `bearing_temperature_c` | °C | Bearing temperature |
| `vibration_mm_s` | mm/s RMS | Vibration velocity |
| `current_a` | A | Motor current |
| `voltage_v` | V | Motor voltage |
| `rpm` | rpm | Rotational speed |
| `load_pct` | % | Load relative to rated load |
| `power_kw` | kW | Active power |
| `operating_state` | string | e.g. `RUNNING` |
| `fault_state` | string | `NORMAL`, `INJECTING`, `ACTIVE`, `RECOVERING` |

## Fault Types

| Fault | Primary Signal Changes |
|-------|------------------------|
| `BEARING_WEAR` | `vibration_mm_s` ↑, `bearing_temperature_c` ↑, `temperature_c` slight ↑ |
| `OVERLOAD` | `load_pct` ↑, `current_a` ↑, `power_kw` ↑, `temperature_c` ↑, `rpm` slight ↓ |
| `OVERHEATING` | `temperature_c` ↑, `bearing_temperature_c` ↑, low vibration change |
| `MISALIGNMENT` | `vibration_mm_s` ↑, `temperature_c` slight ↑, `current_a` slight ↑ |
| `SENSOR_FAILURE` | Stuck, spike, or dropout on a sensor signal |

## Fault Lifecycle

```text
NORMAL
  ↓
INJECTING  (ramp up)
  ↓
ACTIVE     (sustained severity)
  ↓
RECOVERING (ramp down)
  ↓
NORMAL
```

The lifecycle is configurable via `start_tick`, `duration`, `ramp_up_ticks`, `recovery_ticks`, and `severity`.

## MQTT Topic Contract

```text
industrial/devices/{device_id}/telemetry
industrial/devices/{device_id}/status
industrial/devices/{device_id}/events
```

Payload is JSON and validated against the `Telemetry` Pydantic schema before publish.

## Architecture

```text
simulator/
├── simulator/
│   ├── models.py        # IndustrialMotor + Telemetry schema
│   ├── engine.py        # SimulationClock + SimulationEngine
│   ├── faults.py        # Fault models + FaultManager
│   ├── publishers/      # TelemetryPublisher interface + MQTT / memory implementations
│   ├── config.py        # Settings
│   ├── logging_config.py # Structured logging
│   ├── cli.py           # CLI entry point
│   └── __main__.py
├── tests/               # pytest suite
└── scripts/
    └── demo_summary.py  # Terminal demo
```

The simulator core is decoupled from MQTT through the `TelemetryPublisher` interface.

## Configuration

Priority: defaults → environment variables (with `SIMULATOR_` prefix) → CLI flags.

Key settings:

| Environment Variable | CLI Flag | Default |
|----------------------|----------|---------|
| `SIMULATOR_DEVICE_ID` | `--device-id` | `MOTOR-001` |
| `SIMULATOR_SEED` | `--seed` | `42` |
| `SIMULATOR_SAMPLE_INTERVAL` | `--sample-interval` | `1.0` |
| `SIMULATOR_MAX_TICKS` | `--max-ticks` | unlimited |
| `SIMULATOR_MQTT_BROKER_HOST` | `--mqtt-broker-host` | `localhost` |
| `SIMULATOR_MQTT_BROKER_PORT` | `--mqtt-broker-port` | `1883` |
| `SIMULATOR_MQTT_TOPIC_PREFIX` | `--mqtt-topic-prefix` | `industrial` |
| `SIMULATOR_FAULT_TYPE` | `--fault-type` | none |
| `SIMULATOR_FAULT_START_TICK` | `--fault-start-tick` | `30` |
| `SIMULATOR_FAULT_DURATION` | `--fault-duration` | `60` |

## Running Locally

### Without MQTT (terminal demo)

```bash
cd simulator
python -m simulator --no-mqtt --no-realtime --max-ticks 150 \
  --fault-type BEARING_WEAR --fault-start-tick 30 --fault-duration 90
```

### With Mosquitto via Docker Compose

```bash
docker compose up -d mosquitto
cd simulator
python -m simulator --mqtt-broker-host localhost --max-ticks 100
```

### Concise trend demo

```bash
cd simulator
python scripts/demo_summary.py
```

## Testing

```bash
cd simulator
pytest
```

## Known Limitations

- The motor model is synthetic; parameters are representative, not calibrated to a real asset.
- Only one motor instance is supported per CLI invocation in Phase 1.
- MQTT reconnection uses Paho's built-in retry; advanced delivery guarantees are deferred.
- Sensor failure `DROPOUT` mode produces a sentinel negative value that should be handled by consumers.
