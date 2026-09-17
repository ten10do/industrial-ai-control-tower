# MQTT Ingestion Pipeline

## Contract and flow

The backend subscribes at QoS 1 to `industrial/devices/+/telemetry` and processes:

```text
MQTT bytes -> JSON decode -> Pydantic v1.x validation -> topic/device match
           -> registered-device lookup -> PostgreSQL insert -> alarm rules
           -> commit -> Redis latest compare-and-set -> WebSocket latest fan-out
```

The field names, units, and types match `simulator.simulator.models.Telemetry`. Schema versions
with major version 1 are accepted. Unknown majors, invalid JSON, missing/extra fields, wrong
types, naive timestamps, impossible measurement ranges, a topic/payload mismatch, and unknown
devices are rejected. Rejections produce structured logs and a `TELEMETRY_REJECTED` audit event;
payload bodies and secrets are not logged.

## Delivery semantics

MQTT QoS 1 can redeliver. `(device_id, timestamp)` is the Phase 2 idempotency key because the
simulator emits only one aggregate sample per device tick. PostgreSQL enforces it, and duplicates
do not create alarms or WebSocket events. A future source that emits multiple samples at one
instant must add a backward-compatible `message_id` before this policy changes.

Valid out-of-order history is persisted. Redis uses an atomic timestamp comparison, so `t2`
cannot replace cached `t3`. Stale history is not broadcast on the live channel. When Redis is
unavailable, PostgreSQL determines whether the committed row is the latest before broadcast.

## Alarm rules

Phase 2 demonstrates deterministic platform behavior only:

- temperature above 90 °C creates `HIGH_TEMPERATURE` / `CRITICAL`;
- vibration above 7 mm/s RMS creates `HIGH_VIBRATION` / `WARNING`.

These are Alarms, not Incidents or AI Diagnoses. One rule fires at most once for a telemetry row.

## WebSocket backpressure

`/ws/devices/{device_id}/telemetry` has a bounded queue of one per connection. If a client is
slow, its unsent value is replaced by the newer value. Disconnect cleanup is isolated per client;
one failed or slow client does not block another.

## Lifecycle and failure behavior

The MQTT task starts and stops in the FastAPI lifespan and reconnects after broker failures.
PostgreSQL and Redis determine `/ready`; an MQTT outage reports `degraded` but does not kill the
HTTP service. Database, Redis, MQTT, and WebSocket resources are closed during graceful shutdown.
