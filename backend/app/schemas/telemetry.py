"""Simulator-compatible telemetry contract and API schemas."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TelemetryIn(BaseModel):
    """Contract shared semantically with simulator Telemetry v1.x."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    timestamp: datetime
    device_id: str = Field(min_length=1, max_length=100)
    temperature_c: float = Field(ge=-50, le=250)
    bearing_temperature_c: float = Field(ge=-50, le=250)
    vibration_mm_s: float = Field(ge=0, le=200)
    current_a: float = Field(ge=0, le=10_000)
    voltage_v: float = Field(ge=0, le=10_000)
    rpm: int = Field(ge=0, le=100_000)
    load_pct: float = Field(ge=0, le=120)
    power_kw: float = Field(ge=0, le=100_000)
    operating_state: str = Field(min_length=1, max_length=50)
    fault_state: str = Field(min_length=1, max_length=100)

    @field_validator("schema_version")
    @classmethod
    def supported_major_version(cls, value: str) -> str:
        try:
            major = int(value.split(".", maxsplit=1)[0])
        except ValueError as exc:
            raise ValueError("schema_version must be numeric major.minor") from exc
        if major != 1:
            raise ValueError(f"unsupported schema major version: {major}")
        return value

    @field_validator("timestamp")
    @classmethod
    def timezone_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)


class TelemetryRead(TelemetryIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ingested_at: datetime


class TelemetryPage(BaseModel):
    items: list[TelemetryRead]
    next_cursor: datetime | None
