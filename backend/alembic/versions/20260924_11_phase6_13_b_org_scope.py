"""Add the Phase 6.13-B enterprise organization model.

Revision ID: 20260924_11
Revises: 20260924_10

Five tables are created and three permission rows are seeded. No existing
table is altered: the hierarchy is purely additive, and the one association to
existing data is ``device_scopes.device_id`` pointing at the ``devices`` master
record. A device keeps its identity, its telemetry, and its alarms; the new
table only names where it lives.

``CASCADE`` deletes are the rollback story *inside* the model: removing an
organization removes its plants, their areas, the bindings naming them, and
the device associations beneath them. ``downgrade`` removes the structure
itself, in reverse dependency order, and deletes exactly the three permission
rows this migration seeded.

Seeding is duplicated from :data:`app.security.rbac.ROLE_PERMISSIONS` on
purpose, as in every security migration before this one: a migration must keep
producing the rows it produced on the day it ran. The parity test compares the
combined seed of all three security migrations against the code table.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import delete
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260924_11"
down_revision: str | None = "20260924_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)

#: Mirrors the Phase 6.13-B additions to :data:`app.security.rbac.ROLE_PERMISSIONS`.
GRANTS: dict[str, tuple[str, ...]] = {
    "ADMIN": ("org.manage", "scope.manage"),
    "OPERATOR": ("org.read",),
    "VIEWER": ("org.read",),
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
    return dict(rows)


def upgrade() -> None:
    now = datetime.now(UTC)

    op.create_table(
        "organizations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_organizations_name"),
    )

    op.create_table(
        "plants",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "organization_id",
            UUID,
            sa.ForeignKey("organizations.id", ondelete="CASCADE", name="fk_plants_organization_id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "name", name="uq_plants_org_name"),
    )
    op.create_index("ix_plants_organization_id", "plants", ["organization_id"])

    op.create_table(
        "areas",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "plant_id",
            UUID,
            sa.ForeignKey("plants.id", ondelete="CASCADE", name="fk_areas_plant_id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("plant_id", "name", name="uq_areas_plant_name"),
    )
    op.create_index("ix_areas_plant_id", "areas", ["plant_id"])

    op.create_table(
        "user_scopes",
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_user_scopes_user_id"),
            primary_key=True,
        ),
        sa.Column("scope_level", sa.String(20), primary_key=True),
        sa.Column("scope_id", UUID, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_level IN ('ORGANIZATION', 'PLANT', 'AREA')",
            name="ck_user_scopes_level",
        ),
    )
    op.create_index("ix_user_scopes_scope", "user_scopes", ["scope_level", "scope_id"])

    op.create_table(
        "device_scopes",
        sa.Column(
            "device_id",
            sa.String(100),
            sa.ForeignKey(
                "devices.device_id", ondelete="CASCADE", name="fk_device_scopes_device_id"
            ),
            primary_key=True,
        ),
        sa.Column(
            "area_id",
            UUID,
            sa.ForeignKey("areas.id", ondelete="CASCADE", name="fk_device_scopes_area_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_device_scopes_area_id", "device_scopes", ["area_id"])

    _seed(now)


def _seed(now: datetime) -> None:
    permission_names = sorted({name for grants in GRANTS.values() for name in grants})
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
    """Remove the hierarchy and the seeded permissions, leaving nothing behind.

    ``device_scopes`` must go first: it is the only table with a foreign key
    into an existing phase-owned table, and dropping it first means the
    downgrade of an upgraded deployment is a pure subtraction.
    """

    op.drop_index("ix_device_scopes_area_id", table_name="device_scopes")
    op.drop_table("device_scopes")
    op.drop_index("ix_user_scopes_scope", table_name="user_scopes")
    op.drop_table("user_scopes")
    op.drop_index("ix_areas_plant_id", table_name="areas")
    op.drop_table("areas")
    op.drop_index("ix_plants_organization_id", table_name="plants")
    op.drop_table("plants")
    op.drop_table("organizations")

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
