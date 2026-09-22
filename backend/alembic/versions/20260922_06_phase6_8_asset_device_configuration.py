"""Add Phase 6.8 asset hierarchy and versioned device configuration.

Revision ID: 20260922_06
Revises: 20260922_05

Three tables are added and one nullable column is added to ``devices``:

* ``asset_nodes`` is the minimal SITE / LINE location tree.
* ``device_configurations`` holds immutable configuration version snapshots.
* ``device_configuration_runtime_status`` holds observed desired/applied state.
* ``devices.asset_node_id`` links device master rows into the tree.

Device identity is untouched: ``devices.device_id`` remains the single identity
source and ``device_configurations.device_id`` references it. No parallel device
table exists.

The single-published invariant is enforced by the database through a partial
unique index, so two concurrent publishes cannot both remain published.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260922_06"
down_revision: str | None = "20260922_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSON = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "asset_nodes",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("asset_type", sa.String(20), nullable=False),
        sa.Column(
            "parent_id",
            UUID,
            sa.ForeignKey("asset_nodes.id", ondelete="RESTRICT", name="fk_asset_nodes_parent_id"),
        ),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata", JSON, server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("asset_type IN ('SITE', 'LINE')", name="ck_asset_nodes_type"),
        sa.CheckConstraint(
            "(asset_type = 'SITE' AND parent_id IS NULL) "
            "OR (asset_type = 'LINE' AND parent_id IS NOT NULL)",
            name="ck_asset_nodes_parent_shape",
        ),
    )
    op.create_index("ix_asset_nodes_parent_id", "asset_nodes", ["parent_id"])

    op.add_column("devices", sa.Column("asset_node_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_devices_asset_node_id",
        "devices",
        "asset_nodes",
        ["asset_node_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_devices_asset_node_id", "devices", ["asset_node_id"])

    op.create_table(
        "device_configurations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "device_id",
            sa.String(100),
            sa.ForeignKey(
                "devices.device_id",
                ondelete="RESTRICT",
                name="fk_device_configurations_device",
            ),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("protocol", sa.String(20), nullable=False),
        sa.Column("configuration", JSON, nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False, server_default="system"),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("validation_result", JSON, server_default="{}", nullable=False),
        sa.Column("validation_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("device_id", "version", name="uq_device_configurations_device_version"),
        sa.CheckConstraint("version > 0", name="ck_device_configurations_version_positive"),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'VALIDATED', 'PUBLISHED', 'ARCHIVED')",
            name="ck_device_configurations_status",
        ),
        sa.CheckConstraint(
            "(status IN ('PUBLISHED', 'ARCHIVED')) = (published_at IS NOT NULL)",
            name="ck_device_configurations_published_at",
        ),
    )
    op.create_index(
        "ix_device_configurations_device_status",
        "device_configurations",
        ["device_id", "status"],
    )
    op.create_index(
        "uq_device_configurations_single_published",
        "device_configurations",
        ["device_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )

    op.create_table(
        "device_configuration_runtime_status",
        sa.Column(
            "device_id",
            sa.String(100),
            sa.ForeignKey(
                "devices.device_id",
                ondelete="CASCADE",
                name="fk_device_configuration_runtime_status_device",
            ),
            primary_key=True,
        ),
        sa.Column("desired_version", sa.Integer()),
        sa.Column("applied_version", sa.Integer()),
        sa.Column("apply_status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("source", sa.String(20), nullable=False, server_default="none"),
        sa.Column("last_apply_at", sa.DateTime(timezone=True)),
        sa.Column("last_apply_error", sa.Text()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "apply_status IN ('PENDING', 'APPLYING', 'APPLIED', 'FAILED')",
            name="ck_device_configuration_runtime_apply_status",
        ),
        sa.CheckConstraint(
            "source IN ('database', 'bootstrap', 'none')",
            name="ck_device_configuration_runtime_source",
        ),
    )

    op.create_index(
        "ix_audit_events_resource_timestamp",
        "audit_events",
        ["resource", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_resource_timestamp", table_name="audit_events")

    op.drop_table("device_configuration_runtime_status")

    op.drop_index("uq_device_configurations_single_published", table_name="device_configurations")
    op.drop_index("ix_device_configurations_device_status", table_name="device_configurations")
    op.drop_table("device_configurations")

    op.drop_index("ix_devices_asset_node_id", table_name="devices")
    op.drop_constraint("fk_devices_asset_node_id", "devices", type_="foreignkey")
    op.drop_column("devices", "asset_node_id")

    op.drop_index("ix_asset_nodes_parent_id", table_name="asset_nodes")
    op.drop_table("asset_nodes")
