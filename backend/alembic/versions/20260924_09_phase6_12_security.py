"""Add Phase 6.12 identity, authorization, and audit identity columns.

Revision ID: 20260924_09
Revises: 20260923_08

Five tables are created and four nullable columns are added to the existing
``audit_events``.

* ``users``            one identity per row; ``password_hash`` holds a bcrypt
                       digest and the column name says so.
* ``roles``            ADMIN / OPERATOR / VIEWER.
* ``permissions``      the ``resource.action`` vocabulary, including the ``*``
                       literal that ADMIN holds.
* ``user_roles``       identity to role.
* ``role_permissions`` role to permission.

Both link tables carry a composite primary key rather than a surrogate id, so a
duplicate grant is rejected by the database and not merely by the service.

The migration also *seeds* the three default roles and their grants. Seeding in
the migration rather than at application start means authorization is never
briefly undefined on a fresh deployment, and ``alembic downgrade`` removes the
seed with the tables that hold it.

Every addition to ``audit_events`` is nullable with no server default, so rows
written by Phases 2 through 6.11 upgrade untouched and the downgrade is
lossless. ``actor_user_id`` is intentionally **not** a foreign key: an audit
record must outlive the identity it names, and a cascading delete from ``users``
would let user administration rewrite history.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260924_09"
down_revision: str | None = "20260923_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)

#: Mirrors :data:`app.security.rbac.ROLE_PERMISSIONS`. Duplicated here on
#: purpose: a migration must keep producing the schema it produced on the day it
#: ran, so it cannot import a value that a later phase is free to change. A test
#: asserts the seeded rows still equal the code table, which catches drift
#: without letting the migration depend on it.
ROLE_SEED: dict[str, tuple[str, ...]] = {
    "ADMIN": ("*", "user.manage"),
    "OPERATOR": (
        "telemetry.read",
        "dashboard.read",
        "incident.read",
        "incident.create",
        "incident.ack",
        "incident.investigate",
        "incident.resolve",
        "incident.close",
        "incident.reopen",
        "workflow.read",
        "workflow.start",
        "workflow.cancel",
        "approval.read",
        "approval.review",
        "workorder.read",
    ),
    "VIEWER": (
        "telemetry.read",
        "dashboard.read",
        "incident.read",
        "workflow.read",
        "approval.read",
        "workorder.read",
    ),
}

ROLE_DESCRIPTIONS: dict[str, str] = {
    "ADMIN": "Unrestricted platform authority, including user and role management.",
    "OPERATOR": "Runs the incident, workflow, and approval loop for a plant.",
    "VIEWER": "Read-only observer of telemetry, incidents, and decisions.",
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


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("username", sa.String(100), nullable=False),
        sa.Column("email", sa.String(320)),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="ck_users_status"),
    )
    op.create_index("ix_users_status", "users", ["status"])

    op.create_table(
        "roles",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("description", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )

    op.create_table(
        "permissions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_permissions_name"),
    )

    op.create_table(
        "user_roles",
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_user_roles_user_id"),
            primary_key=True,
        ),
        sa.Column(
            "role_id",
            UUID,
            sa.ForeignKey("roles.id", ondelete="CASCADE", name="fk_user_roles_role_id"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_roles_user_id", "user_roles", ["user_id"])

    op.create_table(
        "role_permissions",
        sa.Column(
            "role_id",
            UUID,
            sa.ForeignKey("roles.id", ondelete="CASCADE", name="fk_role_permissions_role_id"),
            primary_key=True,
        ),
        sa.Column(
            "permission_id",
            UUID,
            sa.ForeignKey(
                "permissions.id",
                ondelete="CASCADE",
                name="fk_role_permissions_permission_id",
            ),
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"])

    op.add_column("audit_events", sa.Column("actor_user_id", UUID))
    op.add_column("audit_events", sa.Column("resource_id", sa.String(200)))
    op.add_column("audit_events", sa.Column("ip_address", sa.String(45)))
    op.add_column("audit_events", sa.Column("user_agent", sa.String(400)))
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_resource_id", "audit_events", ["resource_id"])

    _seed()


def _seed() -> None:
    """Insert the default roles, the permission vocabulary, and the grants."""

    permission_names = sorted({name for grants in ROLE_SEED.values() for name in grants})
    permission_ids: dict[str, object] = {name: uuid4() for name in permission_names}
    role_ids: dict[str, object] = {name: uuid4() for name in ROLE_SEED}
    # The security tables carry application-side timestamp defaults, so a seed
    # written in SQL has to state the value explicitly rather than rely on a
    # server default that deliberately does not exist.
    now = datetime.now(UTC)

    op.bulk_insert(
        _roles_table,
        [
            {
                "id": role_ids[name],
                "name": name,
                "description": ROLE_DESCRIPTIONS.get(name, ""),
                "created_at": now,
                "updated_at": now,
            }
            for name in ROLE_SEED
        ],
    )
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
    op.bulk_insert(
        _role_permissions_table,
        [
            {
                "role_id": role_ids[role],
                "permission_id": permission_ids[permission],
                "created_at": now,
            }
            for role, grants in ROLE_SEED.items()
            for permission in grants
        ],
    )


def downgrade() -> None:
    """Remove the security schema and the audit identity columns.

    Dropping ``users`` also drops ``user_roles`` through the foreign key, but the
    link tables are dropped explicitly and first so the intent is readable and
    the order does not depend on cascade behaviour.
    """

    op.drop_index("ix_audit_events_resource_id", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_column("audit_events", "user_agent")
    op.drop_column("audit_events", "ip_address")
    op.drop_column("audit_events", "resource_id")
    op.drop_column("audit_events", "actor_user_id")

    op.drop_index("ix_role_permissions_role_id", table_name="role_permissions")
    op.drop_table("role_permissions")
    op.drop_index("ix_user_roles_user_id", table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_table("users")
