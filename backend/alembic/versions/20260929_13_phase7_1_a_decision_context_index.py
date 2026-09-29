"""Add the Phase 7.1-A decision-context history index.

Revision ID: 20260929_13
Revises: 20260924_12

One additive index is created and nothing is altered or dropped.

``ix_incidents_device_created``
    Supports the Phase 7.1-A bounded historical-incident query, which reads the
    newest incidents for one device while excluding the current incident by
    primary key::

        SELECT * FROM incidents
        WHERE device_id = :device AND id <> :current
        ORDER BY created_at DESC, id DESC
        LIMIT 10

    The pre-existing ``ix_incidents_device_status`` leads on ``device_id`` but
    carries ``status`` as its second column, so it cannot satisfy the
    ``created_at`` ordering. The planner therefore reads every incident for the
    device through a bitmap scan and then sorts, which is linear in the device's
    incident count.

    Measured against 50,000 incidents across 500 devices on PostgreSQL 16: the
    query dropped from 0.250 ms and 108 shared buffers to 0.064 ms and 14 shared
    buffers, a roughly 3.9x execution improvement with 7.7x fewer buffers, and
    the plan changed from a bitmap-heap-scan-plus-sort to an incremental sort
    over an ordered index scan. Because that is a measured, reproducible
    improvement on a hot read path and the index is purely additive, the index is
    taken here rather than deferred.

The index is not unique and enforces no invariant. It changes no query result,
only the plan that produces it. ``downgrade`` drops exactly this index and
leaves every other index and table untouched.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260929_13"
down_revision: str | None = "20260924_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_NAME = "ix_incidents_device_created"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "incidents",
        ["device_id", "created_at"],
        unique=False,
        postgresql_ops={"created_at": "DESC"},
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="incidents")
