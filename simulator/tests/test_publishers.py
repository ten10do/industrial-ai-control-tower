"""Tests for telemetry publishers."""

import json

from simulator.models import IndustrialMotor
from simulator.publishers import InMemoryPublisher, MqttPublisher


class TestInMemoryPublisher:
    """In-memory publisher used for tests and development."""

    def test_captures_telemetry(self) -> None:
        motor = IndustrialMotor(seed=1)
        publisher = InMemoryPublisher()
        telemetry = motor.step()

        publisher.publish(telemetry)

        assert len(publisher.messages) == 1
        assert publisher.messages[0].device_id == "MOTOR-001"


class TestMqttPublisher:
    """MQTT publisher serialization and topic construction."""

    def test_topic_format(self) -> None:
        publisher = MqttPublisher(
            broker_host="localhost",
            broker_port=1883,
            topic_prefix="industrial",
        )
        assert publisher.topic_prefix == "industrial"

    def test_payload_is_valid_json(self) -> None:
        motor = IndustrialMotor(seed=2)
        telemetry = motor.step()
        payload = telemetry.model_dump_json()
        parsed = json.loads(payload)
        assert parsed["device_id"] == "MOTOR-001"
        assert parsed["schema_version"] == "1.0"
        assert "timestamp" in parsed
