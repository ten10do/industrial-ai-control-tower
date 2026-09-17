"""In-memory publisher for tests and offline development."""

from __future__ import annotations

from simulator.models import Telemetry
from simulator.publishers.base import TelemetryPublisher


class InMemoryPublisher(TelemetryPublisher):
    """Captures telemetry in a list for inspection."""

    def __init__(self) -> None:
        self.messages: list[Telemetry] = []

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def publish(self, telemetry: Telemetry) -> None:
        self.messages.append(telemetry)
