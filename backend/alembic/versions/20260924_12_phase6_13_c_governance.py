"""Add the Phase 6.13-C enterprise governance and compliance layer.

Revision ID: 20260924_12
Revises: 20260924_11

Two tables are created and five permission rows are seeded. No existing table
is altered: the governance layer is purely additive and reads the existing
``audit_events`` table instead of duplicating it, so there is exactly one
audit system before and after this migration.

``governance_policies``
    Conditional DENY rules for the Policy Engine. Data only; the engine lives
    in application code and evaluates at request time.

``change_records``
    The change-management ledger and its lifecycle state. It references no
    other table: ``requested_by_user_id`` is an immutable reference in the
    audit-trail tradition, so deleting an identity cannot erase who asked for
    a change.

``downgrade`` drops the two tables and deletes exactly the five permission
rows this migration seeded. Seeding is duplicated from
:data:`app.security.rbac.ROLE_PERMISSIONS` on purpose, as in every security
migration before this one: a migration must keep producing the rows it
produced on the day it ran. The parity test compares the combined seed of all
four security migrations against the code table.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import delete
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260924_12"
down_revision: str | None = "20260924_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)

#: Mirrors the Phase 6.13-C additions to :data:`app.security.rbac.ROLE_PERMISSIONS`.
GRANTS: dict[str, tuple[str, ...]] = {
    "ADMIN": ("governance.manage",),
    "OPERATOR": ("audit.read", "governance.read", "change.read", "change.manage"),
    "VIEWER": ("governance.read", "change.read"),
}

_roles_table = sa.table(
    "roles",
    sa.column("id", UUID),
    sa.column("name", sa.String),
    sa.column("description", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

_permissions_table = sa.table(
    "permissions",
    sa.column("id", UUID),
    sa.column("name", sa.String),
    sa.column("description", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

_role_permissions_table = sa.table(
    "role_permissions",
    sa.column("role_id", UUID),
    sa.column("permission_id", UUID),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def _load_role_ids(connection: sa.Connection) -> dict:
    rows = connection.execute(
        sa.text("SELECT name, id FROM roles WHERE name IN :names").bindparams(
            sa.bindparam("names", expanding=True)
        ),
        {"names": sorted(GRANTS)},
    )
    # dict(rows) is a trap here: CursorResult has a .keys() method, so dict()
    # takes the mapping path and dies on subscript. Unpack the rows instead.
    return {name: role_id for name, role_id in rows}  # noqa: C416


def upgrade() -> None:
    now = datetime.now(UTC)

    op.create_table(
        "governance_policies",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("effect", sa.String(10), nullable=False, server_default="DENY"),
        sa.Column("permission", sa.String(100), nullable=False),
        sa.Column("conditions", postgresql.JSONB, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("effect IN ('DENY')", name="ck_governance_policies_effect"),
    )
    op.create_index("ix_governance_policies_enabled", "governance_policies", ["enabled"])

    op.create_table(
        "change_records",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False, server_default=""),
        sa.Column("change_type", sa.String(20), nullable=False),
        sa.Column("risk_level", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("resource_type", sa.String(100), nullable=True),
        sa.Column("resource_id", sa.String(200), nullable=True),
        sa.Column("requested_by_user_id", UUID, nullable=True),
        sa.Column("requested_by_name", sa.String(100), nullable=True),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'SCHEDULED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')",
            name="ck_change_records_status",
        ),
        sa.CheckConstraint(
            "risk_level IN ('LOW', 'MEDIUM', 'HIGH')",
            name="ck_change_records_risk",
        ),
        sa.CheckConstraint(
            "change_type IN ('CONFIGURATION', 'HARDWARE', 'PROCEDURE')",
            name="ck_change_records_type",
        ),
        sa.CheckConstraint(
            "scheduled_end IS NULL OR scheduled_start IS NULL OR scheduled_end > scheduled_start",
            name="ck_change_records_window",
        ),
    )
    op.create_index("ix_change_records_status", "change_records", ["status"])
    op.create_index(
        "ix_change_records_window", "change_records", ["scheduled_start", "scheduled_end"]
    )

    _seed(now)


def _seed(now: datetime) -> None:
    permission_names = sorted({name for grants in GRANTS.values() for name in grants})
    # noqa: C416 - see _load_role_ids: dict(result) takes the mapping path.
    permission_ids = {name: uuid4() for name in permission_names}

    op.bulk_insert(
        _permissions_table,
        [
            {
                "id": permission_ids[name],
                "name": name,
                "description": "",
                "created_at": now,
                "updated_at": now,
            }
            for name in permission_names
        ],
    )

    connection = op.get_bind()
    role_ids = _load_role_ids(connection)
    op.bulk_insert(
        _role_permissions_table,
        [
            {
                "role_id": role_ids[role],
                "permission_id": permission_ids[permission],
                "created_at": now,
            }
            for role, grants in GRANTS.items()
            for permission in grants
        ],
    )


def downgrade() -> None:
    """Remove the governance tables and the seeded permissions, leaving nothing.

    ``change_records`` references no other table and ``governance_policies``
    neither; the order below is still the reverse of the upgrade so the
    downgrade of an upgraded deployment is a pure subtraction.
    """

    op.drop_index("ix_change_records_window", table_name="change_records")
    op.drop_index("ix_change_records_status", table_name="change_records")
    op.drop_table("change_records")
    op.drop_index("ix_governance_policies_enabled", table_name="governance_policies")
    op.drop_table("governance_policies")

    permission_names = sorted({name for grants in GRANTS.values() for name in grants})
    connection = op.get_bind()
    permission_ids = {  # noqa: C416 - dict(result) takes the mapping path; see _load_role_ids.
        name: permission_id
        for name, permission_id in connection.execute(
            sa.text("SELECT name, id FROM permissions WHERE name IN :names").bindparams(
                sa.bindparam("names", expanding=True)
            ),
            {"names": permission_names},
        )
    }
    if permission_ids:
        connection.execute(
            delete(_role_permissions_table).where(
                _role_permissions_table.c.permission_id.in_(list(permission_ids.values()))
            )
        )
        connection.execute(
            delete(_permissions_table).where(
                _permissions_table.c.id.in_(list(permission_ids.values()))
            )
        )
