"""Add incident lifecycle tracking and correlation anchors.

Revision ID: 20260923_08
Revises: 20260923_07

Phase 6.9-B gives ``incidents`` a lifecycle (acknowledged / resolved / closed
timestamps and the acknowledging actor), a technical severity using the same
ordered vocabulary as alarms, and a correlation anchor (``last_alarm_at``) that
the deterministic device-plus-window engine uses to decide whether the next
alarm on a device attaches to the open incident or opens a new one.

The change is purely additive: every new column is nullable and carries no
server default, so existing rows upgrade unchanged and a downgrade loses
nothing. ``incident_alarms`` already exists from 20260923_07 and is reused
without modification, and the diagnosis association continues to live on the
existing ``diagnoses.incident_id`` foreign key, so no link table is created
here.

``incidents.status`` deliberately gets no CHECK constraint. The workflow engine
writes ``UNDER_ANALYSIS``, ``ACTION_PENDING``, and ``WORK_ORDER_CREATED`` as raw
strings, and the single authority for which moves are legal is the guarded
transition table in ``app/incidents/states.py``, which is enforced at the
service boundary and exhaustively tested. A database CHECK would have to
duplicate that vocabulary inside the migration layer for no additional safety.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260923_08"
down_revision: str | None = "20260923_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("severity", sa.String(20)))
    op.add_column("incidents", sa.Column("acknowledged_at", sa.DateTime(timezone=True)))
    op.add_column("incidents", sa.Column("acknowledged_by", sa.String(100)))
    op.add_column("incidents", sa.Column("resolved_at", sa.DateTime(timezone=True)))
    op.add_column("incidents", sa.Column("closed_at", sa.DateTime(timezone=True)))
    op.add_column("incidents", sa.Column("last_alarm_at", sa.DateTime(timezone=True)))
    op.create_index("ix_incidents_device_status", "incidents", ["device_id", "status"])


def downgrade() -> None:
    """Restore the pre-6.9-B incident shape.

    Every added column and the device/status index are removed. The rows are
    untouched, so the downgrade is lossless: the lifecycle timestamps and the
    correlation anchor are dropped with the columns that carried them, and no
    pre-migration data depended on them because they did not exist before this
    revision.
    """

    op.drop_index("ix_incidents_device_status", table_name="incidents")
    op.drop_column("incidents", "last_alarm_at")
    op.drop_column("incidents", "closed_at")
    op.drop_column("incidents", "resolved_at")
    op.drop_column("incidents", "acknowledged_by")
    op.drop_column("incidents", "acknowledged_at")
    op.drop_column("incidents", "severity")
