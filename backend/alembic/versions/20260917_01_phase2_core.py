"""Create Phase 2 core data schema.

Revision ID: 20260917_01
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260917_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSON = postgresql.JSONB(astext_type=sa.Text())


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", UUID, nullable=False),
        sa.Column("device_id", sa.String(100), nullable=False),
        sa.Column("device_type", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("metadata", JSON, nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", name="uq_devices_device_id"),
    )
    op.create_index("ix_devices_device_id", "devices", ["device_id"])

    op.create_table(
        "telemetry",
        sa.Column("id", UUID, nullable=False),
        sa.Column("device_id", sa.String(100), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temperature_c", sa.Float(), nullable=False),
        sa.Column("bearing_temperature_c", sa.Float(), nullable=False),
        sa.Column("vibration_mm_s", sa.Float(), nullable=False),
        sa.Column("current_a", sa.Float(), nullable=False),
        sa.Column("voltage_v", sa.Float(), nullable=False),
        sa.Column("rpm", sa.Integer(), nullable=False),
        sa.Column("load_pct", sa.Float(), nullable=False),
        sa.Column("power_kw", sa.Float(), nullable=False),
        sa.Column("operating_state", sa.String(50), nullable=False),
        sa.Column("fault_state", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("load_pct >= 0 AND load_pct <= 120", name="ck_telemetry_load_pct"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "timestamp", name="uq_telemetry_device_timestamp"),
    )
    op.create_index("ix_telemetry_device_timestamp", "telemetry", ["device_id", "timestamp"])
    op.create_index("ix_telemetry_timestamp", "telemetry", ["timestamp"])
    op.create_index("ix_telemetry_fault_state", "telemetry", ["fault_state"])

    op.create_table(
        "alarms",
        sa.Column("id", UUID, nullable=False),
        sa.Column("device_id", sa.String(100), nullable=False),
        sa.Column("telemetry_id", UUID),
        sa.Column("rule_id", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleared_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["device_id"], ["devices.device_id"]),
        sa.ForeignKeyConstraint(["telemetry_id"], ["telemetry.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telemetry_id", "rule_id", name="uq_alarm_telemetry_rule"),
    )
    op.create_index("ix_alarm_device_started", "alarms", ["device_id", "started_at"])

    op.create_table(
        "incidents",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "diagnoses",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("incident_id", UUID, sa.ForeignKey("incidents.id")),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "evidence",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("diagnosis_id", UUID, sa.ForeignKey("diagnoses.id")),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "maintenance_plans",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("diagnosis_id", UUID, sa.ForeignKey("diagnoses.id")),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "approvals",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("maintenance_plan_id", UUID, sa.ForeignKey("maintenance_plans.id")),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "work_orders",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("maintenance_plan_id", UUID, sa.ForeignKey("maintenance_plans.id")),
        sa.Column("approval_id", UUID, sa.ForeignKey("approvals.id")),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("trace_id", sa.String(100), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_runs_trace_id", "agent_runs", ["trace_id"])
    op.create_table(
        "audit_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("trace_id", sa.String(100), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource", sa.String(200), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("details", JSON, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_timestamp", "audit_events", ["timestamp"])


def downgrade() -> None:
    for table in (
        "audit_events",
        "agent_runs",
        "work_orders",
        "approvals",
        "maintenance_plans",
        "evidence",
        "diagnoses",
        "incidents",
        "alarms",
        "telemetry",
        "devices",
    ):
        op.drop_table(table)
