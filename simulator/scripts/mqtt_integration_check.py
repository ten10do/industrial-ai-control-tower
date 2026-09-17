"""Verify simulator -> Mosquitto -> subscriber integration."""

from __future__ import annotations

import json
import queue
import time
from typing import Any

import paho.mqtt.client as mqtt

from simulator.engine import SimulationClock, SimulationEngine
from simulator.models import IndustrialMotor
from simulator.publishers import MqttPublisher

BROKER = "localhost"
PORT = 1883
TOPIC = "industrial/devices/MOTOR-001/telemetry"
EXPECTED_MESSAGES = 5

received: queue.Queue[str] = queue.Queue()


def on_connect(
    client: mqtt.Client,
    userdata: None,
    flags: dict[str, Any],
    rc: int,
    properties: Any = None,
) -> None:
    if rc == 0:
        client.subscribe(TOPIC)


def on_message(client: mqtt.Client, userdata: None, msg: mqtt.MQTTMessage) -> None:
    received.put(msg.payload.decode("utf-8"))


client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    client_id="integration-check",
)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT)
client.loop_start()

# Wait for subscription to be active.
time.sleep(1)

motor = IndustrialMotor(device_id="MOTOR-001", seed=42)
clock = SimulationClock(realtime=False)
publisher = MqttPublisher(broker_host=BROKER, broker_port=PORT, client_id="simulator-int-test")
engine = SimulationEngine(motor=motor, clock=clock)
engine.add_handler(publisher.publish)

with publisher:
    engine.run(max_ticks=EXPECTED_MESSAGES)

# Allow messages to arrive.
time.sleep(2)
client.loop_stop()
client.disconnect()

messages: list[str] = []
while not received.empty():
    messages.append(received.get_nowait())

print(f"Received {len(messages)} messages on {TOPIC}")
for m in messages:
    parsed = json.loads(m)
    print(f"  tick: {parsed['timestamp']} vibration={parsed['vibration_mm_s']}")

if len(messages) >= EXPECTED_MESSAGES:
    print("MQTT integration: PASS")
else:
    print("MQTT integration: FAIL")
    raise SystemExit(1)
