"""Extend diagnoses for online ML results.

Revision ID: 20260917_02
Revises: 20260917_01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260917_02"
down_revision: str | None = "20260917_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("diagnoses", sa.Column("device_id", sa.String(100)))
    op.add_column("diagnoses", sa.Column("window_start", sa.DateTime(timezone=True)))
    op.add_column("diagnoses", sa.Column("window_end", sa.DateTime(timezone=True)))
    op.add_column("diagnoses", sa.Column("fault_type", sa.String(100)))
    op.add_column("diagnoses", sa.Column("anomaly_score", sa.Float()))
    op.add_column("diagnoses", sa.Column("confidence", sa.Float()))
    op.add_column("diagnoses", sa.Column("severity", sa.String(20)))
    op.add_column(
        "diagnoses",
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column("diagnoses", sa.Column("model_version", sa.String(100)))
    op.add_column("diagnoses", sa.Column("feature_version", sa.String(100)))
    op.add_column("diagnoses", sa.Column("trace_id", sa.String(100)))
    op.create_foreign_key(
        "fk_diagnoses_device_id", "diagnoses", "devices", ["device_id"], ["device_id"]
    )
    op.create_index("ix_diagnosis_device_created", "diagnoses", ["device_id", "created_at"])
    op.alter_column("diagnoses", "evidence", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_diagnosis_device_created", table_name="diagnoses")
    op.drop_constraint("fk_diagnoses_device_id", "diagnoses", type_="foreignkey")
    for column in (
        "trace_id",
        "feature_version",
        "model_version",
        "evidence",
        "severity",
        "confidence",
        "anomaly_score",
        "fault_type",
        "window_end",
        "window_start",
        "device_id",
    ):
        op.drop_column("diagnoses", column)
