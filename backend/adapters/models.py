"""Protocol-neutral models for industrial device telemetry."""

from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SignalQuality(StrEnum):
    """Quality assigned to a normalized industrial sample."""

    GOOD = "GOOD"
    UNCERTAIN = "UNCERTAIN"
    BAD = "BAD"


class ProtocolType(StrEnum):
    """Protocols understood by the adapter foundation."""

    MQTT = "mqtt"
    OPC_UA = "opcua"
    MODBUS_TCP = "modbus_tcp"
    SIMULATOR = "simulator"


class AdapterStatus(StrEnum):
    """Connection state exposed by an adapter."""

    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    ERROR = "ERROR"


class UnifiedTelemetry(BaseModel):
    """Protocol-neutral telemetry consumed by future backend integrations."""

    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=100)
    timestamp: datetime
    signals: dict[str, float] = Field(min_length=1)
    source_protocol: ProtocolType
    quality: SignalQuality
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("signals")
    @classmethod
    def validate_signals(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not name.strip() for name in value):
            raise ValueError("signal names must not be blank")
        if any(not isfinite(measurement) for measurement in value.values()):
            raise ValueError("signal values must be finite")
        return value


class AdapterHealth(BaseModel):
    """Current health snapshot for a protocol adapter."""

    model_config = ConfigDict(extra="forbid")

    protocol: ProtocolType
    status: AdapterStatus
    last_success: datetime | None = None
    last_error: datetime | None = None
    message: str | None = None
