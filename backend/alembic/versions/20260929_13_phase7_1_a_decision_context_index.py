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

    The index is declared ascending on purpose, with no PostgreSQL-specific
    ``DESC`` op class. PostgreSQL satisfies ``ORDER BY created_at DESC`` with a
    backward index scan over an ascending index, so the descending variant buys
    nothing here while costing a metadata/migration asymmetry: the ORM
    ``Index("ix_incidents_device_created", "device_id", "created_at")`` has no
    way to express the op class, and ``alembic check`` reports the divergence as
    an add/remove pair on every run. Ascending keeps live schema, migration, and
    metadata byte-identical.

    Re-measured on PostgreSQL 16.2 against 50,000 incidents across 500 devices:
    the query is a backward index scan feeding an incremental sort, reading 14
    shared buffers, against 102 shared buffers and a bitmap-heap-scan-plus-top-N
    sort with the index absent. The buffer counts and the plan shape are the
    reproducible evidence; absolute timing tracks cache state, and the ordering
    is served by the index either way. Because the improvement is measured, the
    plan shape is stable, and the index is purely additive, it is taken here
    rather than deferred.

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
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="incidents")
