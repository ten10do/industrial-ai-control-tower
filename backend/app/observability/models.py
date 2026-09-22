"""Phase 6.6 observability persistence models and read contracts.

The observability layer stores a denormalised projection of what the existing
LangGraph workflow already produces. It never becomes a second source of truth
for business state: ``workflow_runs`` remains authoritative, and the records
here are derived from the persisted agent audit trail.

Table names are prefixed with ``observability_`` because Phase 5 already owns a
table named ``agent_runs`` that stores per-agent audit records. Reusing that
name would silently redefine an existing artifact, so the run/step/metric
projection is namespaced instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class ObservabilityStatus(StrEnum):
    """Lifecycle status of one traced workflow execution."""

    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES: frozenset[ObservabilityStatus] = frozenset(
    {
        ObservabilityStatus.SUCCESS,
        ObservabilityStatus.FAILED,
        ObservabilityStatus.BLOCKED,
        ObservabilityStatus.CANCELLED,
    }
)

OPEN_STATUSES: frozenset[ObservabilityStatus] = frozenset(
    {ObservabilityStatus.RUNNING, ObservabilityStatus.WAITING_APPROVAL}
)


class StepStatus(StrEnum):
    """Status of a single agent step inside a traced run."""

    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ObservabilityRun(Base):
    """One traced Agent workflow execution."""

    __tablename__ = "observability_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCESS', 'FAILED', 'BLOCKED', "
            "'WAITING_APPROVAL', 'CANCELLED')",
            name="ck_observability_runs_status",
        ),
        Index("ix_observability_runs_start_time", "start_time"),
        Index("ix_observability_runs_workflow_name", "workflow_name"),
    )

    run_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workflow_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    workflow_name: Mapped[str] = mapped_column(String(100), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(100))
    trace_id: Mapped[str | None] = mapped_column(String(100))
    provider: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="RUNNING")
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[float | None] = mapped_column(Float)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)


class ObservabilityStep(Base):
    """One agent step inside a traced run."""

    __tablename__ = "observability_steps"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'SUCCESS', 'FAILED')",
            name="ck_observability_steps_status",
        ),
        Index("ix_observability_steps_run_sequence", "run_id", "sequence"),
    )

    step_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("observability_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    source_agent_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    input_summary: Mapped[str | None] = mapped_column(Text)
    output_summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class ObservabilityMetric(Base):
    """Token and latency metrics captured for one agent step."""

    __tablename__ = "observability_metrics"

    step_id: Mapped[UUID] = mapped_column(
        ForeignKey("observability_steps.step_id", ondelete="CASCADE"), primary_key=True
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("observability_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    request_count: Mapped[int | None] = mapped_column(Integer)
    schema_retries: Mapped[int | None] = mapped_column(Integer)


@dataclass(frozen=True)
class AgentStepDraft:
    """Materialisation input for one agent step projection."""

    agent_name: str
    sequence: int
    status: str
    start_time: datetime
    end_time: datetime
    latency_ms: float | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    error: str | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    source_agent_run_id: UUID | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    request_count: int | None = None
    schema_retries: int | None = None


class AgentMetricRead(BaseModel):
    """Per-step token and latency metrics."""

    step_id: UUID
    agent_name: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: float | None = None
    request_count: int | None = None
    schema_retries: int | None = None
    token_data_available: bool = False


class AgentStepRead(BaseModel):
    """One agent step of a traced run."""

    step_id: UUID
    agent_name: str
    sequence: int
    status: str
    start_time: datetime
    end_time: datetime
    latency_ms: float | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    error: str | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    metrics: AgentMetricRead | None = None


class AgentRunRead(BaseModel):
    """One traced Agent workflow run."""

    run_id: UUID
    workflow_run_id: UUID | None = None
    workflow_name: str
    device_id: str | None = None
    trace_id: str | None = None
    provider: str | None = None
    model: str | None = None
    status: str
    start_time: datetime
    end_time: datetime | None = None
    latency_ms: float | None = None
    step_count: int = 0
    total_tokens: int | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None


class AgentRunTrace(BaseModel):
    """Full trace of one run: run header plus ordered agent steps."""

    run: AgentRunRead
    steps: list[AgentStepRead] = Field(default_factory=list)


class TokenUsageRead(BaseModel):
    """Aggregate token accounting.

    ``steps_with_token_data`` states how many steps actually reported provider
    usage. Token totals are ``None`` when no step reported usage, so a client
    can distinguish "provider returned nothing" from "zero tokens".
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    steps_with_token_data: int = 0
    steps_total: int = 0


class AgentBreakdownRead(BaseModel):
    """Per-agent aggregate used for execution evaluation."""

    agent_name: str
    steps_total: int
    failures: int
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    total_tokens: int | None = None
    schema_retries: int | None = None


class ObservabilityMetricsRead(BaseModel):
    """Aggregate observability metrics for the dashboard and evaluation."""

    total_runs: int
    runs_running: int
    runs_waiting_approval: int
    runs_today: int
    completed_runs: int
    success_count: int
    failure_count: int
    blocked_count: int
    cancelled_count: int
    success_rate: float | None = None
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    avg_step_latency_ms: float | None = None
    step_status_counts: dict[str, int] = Field(default_factory=dict)
    token_usage: TokenUsageRead = Field(default_factory=TokenUsageRead)
    by_agent: list[AgentBreakdownRead] = Field(default_factory=list)
