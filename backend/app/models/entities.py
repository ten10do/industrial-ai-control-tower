"""Persistence models for Phase 2 data foundations."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, utc_now


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Device(TimestampMixin, Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("device_id", name="uq_devices_device_id"),
        Index("ix_devices_device_id", "device_id"),
        Index("ix_devices_asset_node_id", "asset_node_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    device_id: Mapped[str] = mapped_column(String(100), nullable=False)
    device_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    device_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    asset_node_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("asset_nodes.id", ondelete="RESTRICT", name="fk_devices_asset_node_id"),
        nullable=True,
    )


class Telemetry(Base):
    __tablename__ = "telemetry"
    __table_args__ = (
        UniqueConstraint("device_id", "timestamp", name="uq_telemetry_device_timestamp"),
        CheckConstraint("load_pct >= 0 AND load_pct <= 120", name="ck_telemetry_load_pct"),
        Index("ix_telemetry_device_timestamp", "device_id", "timestamp"),
        Index("ix_telemetry_timestamp", "timestamp"),
        Index("ix_telemetry_fault_state", "fault_state"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.device_id", ondelete="RESTRICT"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    temperature_c: Mapped[float] = mapped_column(Float, nullable=False)
    bearing_temperature_c: Mapped[float] = mapped_column(Float, nullable=False)
    vibration_mm_s: Mapped[float] = mapped_column(Float, nullable=False)
    current_a: Mapped[float] = mapped_column(Float, nullable=False)
    voltage_v: Mapped[float] = mapped_column(Float, nullable=False)
    rpm: Mapped[int] = mapped_column(Integer, nullable=False)
    load_pct: Mapped[float] = mapped_column(Float, nullable=False)
    power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    operating_state: Mapped[str] = mapped_column(String(50), nullable=False)
    fault_state: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class Alarm(Base):
    __tablename__ = "alarms"
    __table_args__ = (
        UniqueConstraint("telemetry_id", "rule_id", name="uq_alarm_telemetry_rule"),
        Index("ix_alarm_device_started", "device_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.device_id"), nullable=False)
    telemetry_id: Mapped[UUID | None] = mapped_column(ForeignKey("telemetry.id"))
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Incident(TimestampMixin, Base):
    __tablename__ = "incidents"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.device_id"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")


class Diagnosis(TimestampMixin, Base):
    __tablename__ = "diagnoses"
    __table_args__ = (Index("ix_diagnosis_device_created", "device_id", "created_at"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    incident_id: Mapped[UUID | None] = mapped_column(ForeignKey("incidents.id"))
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.device_id"))
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="DRAFT")
    fault_type: Mapped[str | None] = mapped_column(String(100))
    anomaly_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    severity: Mapped[str | None] = mapped_column(String(20))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    model_version: Mapped[str | None] = mapped_column(String(100))
    feature_version: Mapped[str | None] = mapped_column(String(100))
    trace_id: Mapped[str | None] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Evidence(TimestampMixin, Base):
    __tablename__ = "evidence"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    diagnosis_id: Mapped[UUID | None] = mapped_column(ForeignKey("diagnoses.id"))
    source: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class MaintenancePlan(TimestampMixin, Base):
    __tablename__ = "maintenance_plans"
    __table_args__ = (UniqueConstraint("workflow_run_id", name="uq_plan_workflow_run"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    diagnosis_id: Mapped[UUID | None] = mapped_column(ForeignKey("diagnoses.id"))
    workflow_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("workflow_runs.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    plan_hash: Mapped[str | None] = mapped_column(String(64))
    objective: Mapped[str | None] = mapped_column(Text)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    tools_required: Mapped[list[str]] = mapped_column(JSONB, default=list)
    estimated_risk: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Approval(TimestampMixin, Base):
    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("workflow_run_id", name="uq_approval_workflow_run"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    maintenance_plan_id: Mapped[UUID | None] = mapped_column(ForeignKey("maintenance_plans.id"))
    workflow_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("workflow_runs.id"))
    decision: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    actor: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    plan_hash: Mapped[str | None] = mapped_column(String(64))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class WorkOrder(TimestampMixin, Base):
    __tablename__ = "work_orders"
    __table_args__ = (UniqueConstraint("workflow_run_id", name="uq_work_order_workflow_run"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workflow_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("workflow_runs.id"))
    maintenance_plan_id: Mapped[UUID | None] = mapped_column(ForeignKey("maintenance_plans.id"))
    approval_id: Mapped[UUID | None] = mapped_column(ForeignKey("approvals.id"))
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.device_id"))
    incident_id: Mapped[UUID | None] = mapped_column(ForeignKey("incidents.id"))
    diagnosis_id: Mapped[UUID | None] = mapped_column(ForeignKey("diagnoses.id"))
    title: Mapped[str | None] = mapped_column(String(300))
    priority: Mapped[str | None] = mapped_column(String(20))
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, default=list)
    safety_requirements: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    workflow_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    input_ref: Mapped[str | None] = mapped_column(String(200))
    output_ref: Mapped[str | None] = mapped_column(String(200))
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkflowRun(TimestampMixin, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_workflow_runs_idempotency_key"),
        Index("ix_workflow_runs_incident_status", "incident_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    incident_id: Mapped[UUID] = mapped_column(ForeignKey("incidents.id"), nullable=False)
    diagnosis_id: Mapped[UUID] = mapped_column(ForeignKey("diagnoses.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.device_id"), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    workflow_version: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_versions: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    current_stage: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_timestamp", "timestamp"),
        Index("ix_audit_events_resource_timestamp", "resource", "timestamp"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("sha256", name="uq_knowledge_documents_sha256"),)

    document_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    vendor: Mapped[str] = mapped_column(String(200), nullable=False)
    document_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    equipment_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(200), index=True)
    revision: Mapped[str | None] = mapped_column(String(200))
    publication_date: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    license_note: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    corpus_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (Index("ix_knowledge_chunks_document_index", "document_id", "chunk_index"),)

    chunk_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.document_id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(500))
    heading: Mapped[str | None] = mapped_column(String(500))
    document_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    equipment_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(200), index=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[str | None] = mapped_column(String(200))
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(384), nullable=False)


class RetrievalRun(Base):
    __tablename__ = "retrieval_runs"
    __table_args__ = (Index("ix_retrieval_runs_timestamp", "timestamp"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    query: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(100), nullable=False)
    corpus_version: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(100), nullable=False)
    candidate_chunks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    selected_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    sufficiency_result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
