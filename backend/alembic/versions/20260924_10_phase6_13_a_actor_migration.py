"""Seed the Phase 6.13-A permission vocabulary and its default grants.

Revision ID: 20260924_10
Revises: 20260924_09

Phase 6.13-A migrates the alarm, alarm-rule, asset, device-configuration,
connectivity, and observability routes behind ``require_permission``. The
database is the authorization source of truth at request time, so the new
``resource.action`` names and the ``OPERATOR`` / ``VIEWER`` grants must exist as
rows before the first request that enforces them; this migration seeds exactly
that, and nothing else.

No schema changes are needed: ``permissions`` and ``role_permissions`` already
exist from Phase 6.12. ``ADMIN`` holds the ``*`` wildcard, so it needs no new
grant rows.

The seed is duplicated from :data:`app.security.rbac.ROLE_PERMISSIONS` on
purpose, in the same way the Phase 6.12 migration duplicated its own: a
migration must keep producing the rows it produced on the day it ran, so it
cannot import a value a later phase is free to change. A test asserts the
combined seed of both migrations still equals the code table, which catches
drift without letting the migration depend on it.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import delete
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260924_10"
down_revision: str | None = "20260924_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)

#: Mirrors the Phase 6.13-A additions to :data:`app.security.rbac.ROLE_PERMISSIONS`.
#: Only the *new* rows are listed here; the Phase 6.12 rows are already seeded
#: and are left untouched.
GRANTS: dict[str, tuple[str, ...]] = {
    "OPERATOR": (
        "alarm.read",
        "alarm.ack",
        "alarm.clear",
        "alarmrule.read",
        "alarmrule.create",
        "alarmrule.update",
        "asset.read",
        "asset.manage",
        "config.read",
        "config.write",
        "config.publish",
        "connectivity.read",
        "connectivity.control",
        "observability.read",
    ),
    "VIEWER": (
        "alarm.read",
        "alarmrule.read",
        "asset.read",
        "config.read",
        "connectivity.read",
        "observability.read",
    ),
}

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
    return dict(rows)


def upgrade() -> None:
    """Insert the new permissions and grant them to OPERATOR and VIEWER."""

    permission_names = sorted({name for grants in GRANTS.values() for name in grants})
    permission_ids = {name: uuid4() for name in permission_names}
    # The security tables carry application-side timestamp defaults, so a seed
    # written in SQL has to state the value explicitly rather than rely on a
    # server default that deliberately does not exist.
    now = datetime.now(UTC)

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
    """Remove the Phase 6.13-A grants and permission rows.

    Only rows this migration introduced are deleted: the Phase 6.12 vocabulary
    and grants are left exactly as that migration seeded them.
    """

    permission_names = sorted({name for grants in GRANTS.values() for name in grants})
    connection = op.get_bind()
    permission_ids = dict(
        connection.execute(
            sa.text("SELECT name, id FROM permissions WHERE name IN :names").bindparams(
                sa.bindparam("names", expanding=True)
            ),
            {"names": permission_names},
        )
    )
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
