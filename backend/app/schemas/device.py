"""Device API schemas."""

from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

DeviceStatus = Literal["ACTIVE", "INACTIVE", "DECOMMISSIONED"]


class DeviceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    device_type: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    status: DeviceStatus = "ACTIVE"
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeviceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_type: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: DeviceStatus | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> Self:
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"'{field}' cannot be null")
        return self


class DeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_id: str
    device_type: str
    name: str
    status: str
    metadata: dict[str, Any] = Field(validation_alias="device_metadata")
    created_at: datetime
    updated_at: datetime
