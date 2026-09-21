"""Add Phase 5 decision workflow, approval, work order, and LangGraph checkpoints.

Revision ID: 20260920_04
Revises: 20260920_03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260920_04"
down_revision: str | None = "20260920_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSON = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("incidents", sa.Column("device_id", sa.String(100)))
    op.create_foreign_key(
        "fk_incidents_device", "incidents", "devices", ["device_id"], ["device_id"]
    )
    op.create_index("ix_incidents_device_id", "incidents", ["device_id"])

    op.create_table(
        "workflow_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("incident_id", UUID, sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("diagnosis_id", UUID, sa.ForeignKey("diagnoses.id"), nullable=False),
        sa.Column("device_id", sa.String(100), sa.ForeignKey("devices.device_id"), nullable=False),
        sa.Column("trace_id", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("workflow_version", sa.String(100), nullable=False),
        sa.Column("policy_version", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("prompt_versions", JSON, nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("current_stage", sa.String(40), nullable=False),
        sa.Column("state", JSON, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("errors", JSON, nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_workflow_runs_idempotency_key"),
    )
    op.create_index("ix_workflow_runs_trace_id", "workflow_runs", ["trace_id"])
    op.create_index("ix_workflow_runs_incident_status", "workflow_runs", ["incident_id", "status"])

    op.add_column("maintenance_plans", sa.Column("workflow_run_id", UUID))
    op.add_column(
        "maintenance_plans", sa.Column("version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("maintenance_plans", sa.Column("plan_hash", sa.String(64)))
    op.add_column("maintenance_plans", sa.Column("objective", sa.Text()))
    op.add_column(
        "maintenance_plans", sa.Column("steps", JSON, server_default="[]", nullable=False)
    )
    op.add_column(
        "maintenance_plans", sa.Column("tools_required", JSON, server_default="[]", nullable=False)
    )
    op.add_column("maintenance_plans", sa.Column("estimated_risk", sa.String(20)))
    op.create_foreign_key(
        "fk_plan_workflow", "maintenance_plans", "workflow_runs", ["workflow_run_id"], ["id"]
    )
    op.create_unique_constraint("uq_plan_workflow_run", "maintenance_plans", ["workflow_run_id"])

    op.add_column("approvals", sa.Column("workflow_run_id", UUID))
    op.add_column("approvals", sa.Column("actor", sa.String(200)))
    op.add_column("approvals", sa.Column("reason", sa.Text()))
    op.add_column(
        "approvals", sa.Column("plan_version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("approvals", sa.Column("plan_hash", sa.String(64)))
    op.add_column("approvals", sa.Column("decided_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_approval_workflow", "approvals", "workflow_runs", ["workflow_run_id"], ["id"]
    )
    op.create_unique_constraint("uq_approval_workflow_run", "approvals", ["workflow_run_id"])

    for name, type_ in (
        ("workflow_run_id", UUID),
        ("device_id", sa.String(100)),
        ("incident_id", UUID),
        ("diagnosis_id", UUID),
        ("title", sa.String(300)),
        ("priority", sa.String(20)),
    ):
        op.add_column("work_orders", sa.Column(name, type_))
    op.add_column("work_orders", sa.Column("plan", JSON, server_default="{}", nullable=False))
    op.add_column(
        "work_orders", sa.Column("evidence_refs", JSON, server_default="[]", nullable=False)
    )
    op.add_column(
        "work_orders", sa.Column("safety_requirements", JSON, server_default="[]", nullable=False)
    )
    op.create_foreign_key(
        "fk_work_order_workflow", "work_orders", "workflow_runs", ["workflow_run_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_work_order_device", "work_orders", "devices", ["device_id"], ["device_id"]
    )
    op.create_foreign_key(
        "fk_work_order_incident", "work_orders", "incidents", ["incident_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_work_order_diagnosis", "work_orders", "diagnoses", ["diagnosis_id"], ["id"]
    )
    op.create_unique_constraint("uq_work_order_workflow_run", "work_orders", ["workflow_run_id"])

    for name, type_ in (
        ("workflow_run_id", UUID),
        ("provider", sa.String(100)),
        ("model", sa.String(200)),
        ("prompt_version", sa.String(100)),
        ("input_ref", sa.String(200)),
        ("output_ref", sa.String(200)),
        ("latency_ms", sa.Float()),
        ("input_tokens", sa.Integer()),
        ("output_tokens", sa.Integer()),
        ("error", sa.Text()),
    ):
        op.add_column("agent_runs", sa.Column(name, type_))
    op.add_column("agent_runs", sa.Column("tool_calls", JSON, server_default="[]", nullable=False))
    op.create_foreign_key(
        "fk_agent_run_workflow", "agent_runs", "workflow_runs", ["workflow_run_id"], ["id"]
    )
    op.create_index("ix_agent_runs_workflow_run_id", "agent_runs", ["workflow_run_id"])

    op.execute("CREATE TABLE checkpoint_migrations (v INTEGER PRIMARY KEY)")
    op.execute(
        "CREATE TABLE checkpoints ("
        "thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '', "
        "checkpoint_id TEXT NOT NULL, parent_checkpoint_id TEXT, type TEXT, "
        "checkpoint JSONB NOT NULL, metadata JSONB NOT NULL DEFAULT '{}', "
        "PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id))"
    )
    op.execute(
        "CREATE TABLE checkpoint_blobs ("
        "thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '', "
        "channel TEXT NOT NULL, version TEXT NOT NULL, type TEXT NOT NULL, blob BYTEA, "
        "PRIMARY KEY (thread_id, checkpoint_ns, channel, version))"
    )
    op.execute(
        "CREATE TABLE checkpoint_writes ("
        "thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL DEFAULT '', "
        "checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL, idx INTEGER NOT NULL, "
        "channel TEXT NOT NULL, "
        "type TEXT, blob BYTEA NOT NULL, task_path TEXT NOT NULL DEFAULT '', "
        "PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx))"
    )
    for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
        op.create_index(f"{table}_thread_id_idx", table, ["thread_id"])
    op.execute("INSERT INTO checkpoint_migrations(v) SELECT generate_series(0, 9)")


def downgrade() -> None:
    for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints", "checkpoint_migrations"):
        op.drop_table(table)
    op.drop_index("ix_agent_runs_workflow_run_id", table_name="agent_runs")
    op.drop_constraint("fk_agent_run_workflow", "agent_runs", type_="foreignkey")
    for column in (
        "tool_calls",
        "error",
        "output_tokens",
        "input_tokens",
        "latency_ms",
        "output_ref",
        "input_ref",
        "prompt_version",
        "model",
        "provider",
        "workflow_run_id",
    ):
        op.drop_column("agent_runs", column)
    op.drop_constraint("uq_work_order_workflow_run", "work_orders", type_="unique")
    for constraint in (
        "fk_work_order_diagnosis",
        "fk_work_order_incident",
        "fk_work_order_device",
        "fk_work_order_workflow",
    ):
        op.drop_constraint(constraint, "work_orders", type_="foreignkey")
    for column in (
        "safety_requirements",
        "evidence_refs",
        "plan",
        "priority",
        "title",
        "diagnosis_id",
        "incident_id",
        "device_id",
        "workflow_run_id",
    ):
        op.drop_column("work_orders", column)
    op.drop_constraint("uq_approval_workflow_run", "approvals", type_="unique")
    op.drop_constraint("fk_approval_workflow", "approvals", type_="foreignkey")
    for column in ("decided_at", "plan_hash", "plan_version", "reason", "actor", "workflow_run_id"):
        op.drop_column("approvals", column)
    op.drop_constraint("uq_plan_workflow_run", "maintenance_plans", type_="unique")
    op.drop_constraint("fk_plan_workflow", "maintenance_plans", type_="foreignkey")
    for column in (
        "estimated_risk",
        "tools_required",
        "steps",
        "objective",
        "plan_hash",
        "version",
        "workflow_run_id",
    ):
        op.drop_column("maintenance_plans", column)
    op.drop_table("workflow_runs")
    op.drop_index("ix_incidents_device_id", table_name="incidents")
    op.drop_constraint("fk_incidents_device", "incidents", type_="foreignkey")
    op.drop_column("incidents", "device_id")
