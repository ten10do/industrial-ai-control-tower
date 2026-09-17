# Industrial AI Control Tower — Simulator

Synthetic industrial motor telemetry simulator with MQTT publishing and fault injection.

## Scope

This simulator produces structured telemetry for an `IndustrialMotor` and publishes it over MQTT. It is an engineering simulation, not a precise digital twin of a specific real motor.

## Telemetry Fields

| Field | Unit | Description |
|-------|------|-------------|
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
| `fault_state` | string | Lifecycle stage of active faults |

## Fault Types

| Fault | Primary Signal Changes |
|-------|------------------------|
| `BEARING_WEAR` | vibration ↑, bearing_temperature ↑ |
| `OVERLOAD` | load_pct ↑, current_a ↑, power_kw ↑, temperature ↑, rpm slight ↓ |
| `OVERHEATING` | temperature ↑, bearing_temperature ↑ (low vibration) |
| `MISALIGNMENT` | vibration ↑, temperature slight ↑, current slight ↑ |
| `SENSOR_FAILURE` | stuck/spike/dropout on a sensor signal |

## MQTT Topic Contract

```text
industrial/devices/{device_id}/telemetry
industrial/devices/{device_id}/status
industrial/devices/{device_id}/events
```

## Run

```bash
python -m simulator
```

With options:

```bash
python -m simulator \
  --device-id MOTOR-001 \
  --seed 42 \
  --sample-interval 1.0 \
  --max-ticks 200 \
  --fault-type BEARING_WEAR \
  --fault-start-tick 30 \
  --fault-duration 60
```

## Test

```bash
pytest
```

## Lint

```bash
ruff check .
ruff format --check .
```

## Type Check

```bash
mypy simulator tests
```
