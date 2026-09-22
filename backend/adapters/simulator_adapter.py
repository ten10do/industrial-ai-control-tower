"""Adapter for the existing simulator telemetry payload."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from adapters.base import IndustrialProtocolAdapter
from adapters.exceptions import AdapterConnectionError, AdapterReadError
from adapters.models import (
    AdapterHealth,
    AdapterStatus,
    ProtocolType,
    SignalQuality,
    UnifiedTelemetry,
)

SimulatorSource = Callable[[], Mapping[str, Any]]

_SIGNAL_FIELDS = {
    "temperature_c": "temperature",
    "bearing_temperature_c": "bearing_temperature",
    "vibration_mm_s": "vibration",
    "current_a": "current",
    "voltage_v": "voltage",
    "rpm": "rpm",
    "load_pct": "load",
    "power_kw": "power",
}


class SimulatorAdapter(IndustrialProtocolAdapter):
    """Normalize samples produced by the current industrial motor simulator."""

    def __init__(self, source: SimulatorSource) -> None:
        if not callable(source):
            raise ValueError("source must be callable")
        self._source = source
        self._status = AdapterStatus.DISCONNECTED
        self._last_success: datetime | None = None
        self._last_error: datetime | None = None
        self._message: str | None = None

    @property
    def protocol(self) -> ProtocolType:
        return ProtocolType.SIMULATOR

    async def connect(self) -> None:
        self._status = AdapterStatus.CONNECTED
        self._message = None

    async def disconnect(self) -> None:
        self._status = AdapterStatus.DISCONNECTED
        self._message = None

    async def read(self) -> UnifiedTelemetry:
        if self._status is not AdapterStatus.CONNECTED:
            raise AdapterConnectionError("Simulator adapter is not connected.")
        try:
            payload = self._source()
            signals = {
                normalized: float(payload[source]) for source, normalized in _SIGNAL_FIELDS.items()
            }
            telemetry = UnifiedTelemetry(
                device_id=str(payload["device_id"]),
                timestamp=payload["timestamp"],
                signals=signals,
                source_protocol=self.protocol,
                quality=SignalQuality.GOOD,
                metadata={
                    "schema_version": payload.get("schema_version", "1.0"),
                    "operating_state": payload.get("operating_state"),
                    "fault_state": payload.get("fault_state"),
                },
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            self._status = AdapterStatus.ERROR
            self._last_error = datetime.now(UTC)
            self._message = "Simulator payload could not be normalized."
            raise AdapterReadError(self._message) from exc
        self._status = AdapterStatus.CONNECTED
        self._last_success = datetime.now(UTC)
        self._message = None
        return telemetry

    def health(self) -> AdapterHealth:
        return AdapterHealth(
            protocol=self.protocol,
            status=self._status,
            last_success=self._last_success,
            last_error=self._last_error,
            message=self._message,
        )
