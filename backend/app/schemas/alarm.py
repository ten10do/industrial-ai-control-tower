"""Alarm response schema."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AlarmRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_id: str
    telemetry_id: UUID | None
    rule_id: str
    severity: str
    status: str
    message: str
    started_at: datetime
    cleared_at: datetime | None
