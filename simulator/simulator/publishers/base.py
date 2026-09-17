"""Publisher interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType

from simulator.models import Telemetry


class TelemetryPublisher(ABC):
    """Abstract transport for telemetry. Implementations may use MQTT, files, or memory."""

    @abstractmethod
    def connect(self) -> None:
        """Prepare the transport for publishing."""

    @abstractmethod
    def disconnect(self) -> None:
        """Flush and close the transport gracefully."""

    @abstractmethod
    def publish(self, telemetry: Telemetry) -> None:
        """Publish a single telemetry sample."""

    def publish_status(self, device_id: str, status: str) -> None:
        """Publish a device status message. Default is no-op."""
        return None

    def __enter__(self) -> TelemetryPublisher:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.disconnect()
