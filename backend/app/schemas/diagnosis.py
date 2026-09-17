"""Diagnosis REST schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.ml.runtime import DiagnosticEvidence


class DiagnosisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_id: str
    window_start: datetime
    window_end: datetime
    status: str
    fault_type: str | None
    anomaly_score: float | None
    confidence: float | None
    severity: str | None
    evidence: list[DiagnosticEvidence]
    model_version: str | None
    feature_version: str | None
    trace_id: str | None
    created_at: datetime


class DiagnosisPage(BaseModel):
    items: list[DiagnosisRead]
    next_cursor: datetime | None
