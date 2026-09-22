"""Add Phase 6.6 agent observability trace, step, and metric tables.

Revision ID: 20260922_05
Revises: 20260920_04

The observability projection lives in its own namespace. Phase 5 already owns a
table named ``agent_runs`` that stores per-agent audit records, and reusing that
name would redefine an existing frozen artifact. No existing table is altered by
this revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260922_05"
down_revision: str | None = "20260920_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSON = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "observability_runs",
        sa.Column("run_id", UUID, primary_key=True),
        sa.Column("workflow_run_id", UUID, sa.ForeignKey("workflow_runs.id")),
        sa.Column("workflow_name", sa.String(100), nullable=False),
        sa.Column("device_id", sa.String(100)),
        sa.Column("trace_id", sa.String(100)),
        sa.Column("provider", sa.String(100)),
        sa.Column("model", sa.String(200)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("result", JSON, server_default="{}", nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCESS', 'FAILED', 'BLOCKED', "
            "'WAITING_APPROVAL', 'CANCELLED')",
            name="ck_observability_runs_status",
        ),
    )
    op.create_index(
        "ix_observability_runs_workflow_run_id", "observability_runs", ["workflow_run_id"]
    )
    op.create_index("ix_observability_runs_start_time", "observability_runs", ["start_time"])
    op.create_index("ix_observability_runs_workflow_name", "observability_runs", ["workflow_name"])

    op.create_table(
        "observability_steps",
        sa.Column("step_id", UUID, primary_key=True),
        sa.Column(
            "run_id",
            UUID,
            sa.ForeignKey("observability_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_agent_run_id", UUID),
        sa.Column("sequence", sa.Integer(), server_default="0", nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(100)),
        sa.Column("model", sa.String(200)),
        sa.Column("prompt_version", sa.String(100)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("input_summary", sa.Text()),
        sa.Column("output_summary", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCESS', 'FAILED')",
            name="ck_observability_steps_status",
        ),
    )
    op.create_index(
        "ix_observability_steps_run_sequence", "observability_steps", ["run_id", "sequence"]
    )

    op.create_table(
        "observability_metrics",
        sa.Column(
            "step_id",
            UUID,
            sa.ForeignKey("observability_steps.step_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "run_id",
            UUID,
            sa.ForeignKey("observability_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("request_count", sa.Integer()),
        sa.Column("schema_retries", sa.Integer()),
    )
    op.create_index("ix_observability_metrics_run_id", "observability_metrics", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_observability_metrics_run_id", table_name="observability_metrics")
    op.drop_table("observability_metrics")
    op.drop_index("ix_observability_steps_run_sequence", table_name="observability_steps")
    op.drop_table("observability_steps")
    op.drop_index("ix_observability_runs_workflow_name", table_name="observability_runs")
    op.drop_index("ix_observability_runs_start_time", table_name="observability_runs")
    op.drop_index("ix_observability_runs_workflow_run_id", table_name="observability_runs")
    op.drop_table("observability_runs")
