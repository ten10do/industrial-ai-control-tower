"""Add the alarm rule registry, the incident linkage, and the alarm lifecycle.

Revision ID: 20260923_07
Revises: 20260922_06

Two tables are added and five columns are added to ``alarms``:

* ``alarm_rules`` promotes the two thresholds that used to be string literals in
  ``TelemetryService._apply_alarm_rules`` into declarative data. The two original
  rules are seeded here with their exact original thresholds, severities, and
  operator, so behaviour after this migration is the behaviour before it and a
  threshold change stops requiring a redeploy.
* ``incident_alarms`` records which alarm instances contributed to which
  incident. No incident is created by this revision.

The ``alarms`` table is promoted from a per-sample rule trigger log to an active
condition instance registry. Two properties make that promotion safe on a
populated database.

**Row count is preserved.** No row is deleted. ``uq_alarm_telemetry_rule`` is
retained, so the original per-sample uniqueness guarantee still holds and a
downgrade can always recreate the pre-migration shape without a data loss.

**Pre-existing duplicate open rows are consolidated first.** Before this revision
one sustained condition produced one row per telemetry sample, so a device that
overheated for an hour could hold hundreds of ``ACTIVE`` rows sharing a device and
a rule. The partial unique index that enforces "at most one open instance per
device and rule" could not be built over that data. The backfill therefore runs
before the index, and it consolidates deterministically:

* the earliest row of each group stays open and absorbs the group, taking
  ``occurrence_count`` equal to the number of rows that were in it, and
  ``last_triggered_at`` equal to the group's most recent ``started_at``;
* every later row of the group is relabelled ``CLEARED`` with
  ``clear_reason = 'SUPERSEDED_ON_MIGRATION_20260923_07'``, keeping its own
  ``started_at`` as both its ``last_triggered_at`` and its ``cleared_at``.

The relabelled rows are marked rather than removed, so the breach history that
existed before the upgrade is still readable afterwards. The asymmetry worth
recording is that ``downgrade`` restores the schema but cannot restore those
statuses, because the pre-migration status of a relabelled row is not recoverable
from the consolidated shape. Schema rollback is complete; row status rollback is
not, and the affected rows are identifiable by their ``clear_reason``.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260923_07"
down_revision: str | None = "20260922_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)

SUPERSEDED_REASON = "SUPERSEDED_ON_MIGRATION_20260923_07"

ALARM_RULE_COLUMNS = (
    "id",
    "name",
    "description",
    "device_type",
    "signal_name",
    "operator",
    "threshold",
    "severity",
    "priority",
    "enabled",
    "created_at",
    "updated_at",
)

#: exact reproduction of the two rules that were hardcoded before this revision
SEED_RULES: tuple[dict[str, object], ...] = (
    {
        "id": "HIGH_TEMPERATURE",
        "name": "High temperature",
        "description": (
            "Winding temperature above the critical limit. Seeded by migration "
            "20260923_07 from the threshold previously hardcoded in the telemetry "
            "ingestion path."
        ),
        "device_type": None,
        "signal_name": "temperature",
        "operator": "GT",
        "threshold": 90.0,
        "severity": "CRITICAL",
        "priority": "URGENT",
        "enabled": True,
    },
    {
        "id": "HIGH_VIBRATION",
        "name": "High vibration",
        "description": (
            "Bearing vibration above the warning limit. Seeded by migration "
            "20260923_07 from the threshold previously hardcoded in the telemetry "
            "ingestion path."
        ),
        "device_type": None,
        "signal_name": "vibration",
        "operator": "GT",
        "threshold": 7.0,
        "severity": "WARNING",
        "priority": "HIGH",
        "enabled": True,
    },
)

#: Consolidate pre-existing open duplicates into one instance per device and rule.
#: Order inside a group is by ``started_at`` then ``id`` so the outcome is
#: reproducible and does not depend on physical row order.
_CONSOLIDATE_DUPLICATES = sa.text(
    """
    UPDATE alarms AS a
    SET occurrence_count = CASE WHEN r.rn = 1 THEN r.group_size ELSE 1 END,
        last_triggered_at = CASE WHEN r.rn = 1 THEN r.group_last ELSE a.started_at END,
        status = CASE WHEN r.rn = 1 THEN a.status ELSE 'CLEARED' END,
        cleared_at = CASE WHEN r.rn = 1 THEN a.cleared_at ELSE a.started_at END,
        clear_reason = CASE WHEN r.rn = 1 THEN a.clear_reason ELSE :reason END
    FROM (
        SELECT id,
               row_number() OVER (
                   PARTITION BY device_id, rule_id ORDER BY started_at ASC, id ASC
               ) AS rn,
               count(*) OVER (PARTITION BY device_id, rule_id) AS group_size,
               max(started_at) OVER (PARTITION BY device_id, rule_id) AS group_last
        FROM alarms
        WHERE status <> 'CLEARED'
    ) AS r
    WHERE a.id = r.id
    """
)


def upgrade() -> None:
    op.create_table(
        "alarm_rules",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("device_type", sa.String(50)),
        sa.Column("signal_name", sa.String(50), nullable=False),
        sa.Column("operator", sa.String(10), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False, server_default="MEDIUM"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "signal_name IN ('temperature', 'bearing_temperature', 'vibration', "
            "'current', 'voltage', 'rpm', 'load', 'power')",
            name="ck_alarm_rules_signal_name",
        ),
        sa.CheckConstraint(
            "operator IN ('GT', 'GTE', 'LT', 'LTE', 'EQ', 'NE')",
            name="ck_alarm_rules_operator",
        ),
        sa.CheckConstraint(
            "severity IN ('INFO', 'MINOR', 'WARNING', 'MAJOR', 'CRITICAL')",
            name="ck_alarm_rules_severity",
        ),
        sa.CheckConstraint(
            "priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')",
            name="ck_alarm_rules_priority",
        ),
    )
    op.create_index("ix_alarm_rules_enabled_signal", "alarm_rules", ["enabled", "signal_name"])

    rule_table = sa.table("alarm_rules", *(sa.column(name) for name in ALARM_RULE_COLUMNS))
    seeded_at = datetime.now(UTC)
    op.bulk_insert(
        rule_table,
        [{**row, "created_at": seeded_at, "updated_at": seeded_at} for row in SEED_RULES],
    )

    op.add_column("alarms", sa.Column("acknowledged_at", sa.DateTime(timezone=True)))
    op.add_column("alarms", sa.Column("acknowledged_by", sa.String(100)))
    op.add_column("alarms", sa.Column("clear_reason", sa.Text()))
    op.add_column(
        "alarms",
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("alarms", sa.Column("last_triggered_at", sa.DateTime(timezone=True)))

    # Backfill before the index. The partial unique index cannot be created while a
    # device and rule still hold more than one open row.
    op.get_bind().execute(_CONSOLIDATE_DUPLICATES, {"reason": SUPERSEDED_REASON})

    op.create_check_constraint(
        "ck_alarms_occurrence_count",
        "alarms",
        "occurrence_count >= 1",
    )
    op.create_check_constraint(
        "ck_alarms_status",
        "alarms",
        "status IN ('ACTIVE', 'ACKNOWLEDGED', 'CLEARED')",
    )
    op.create_index(
        "uq_alarms_open_device_rule",
        "alarms",
        ["device_id", "rule_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'CLEARED'"),
    )
    op.create_index("ix_alarms_open_status_device", "alarms", ["status", "device_id"])

    op.create_table(
        "incident_alarms",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "incident_id",
            UUID,
            sa.ForeignKey(
                "incidents.id",
                ondelete="CASCADE",
                name="fk_incident_alarms_incident_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "alarm_id",
            UUID,
            sa.ForeignKey("alarms.id", ondelete="CASCADE", name="fk_incident_alarms_alarm_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("incident_id", "alarm_id", name="uq_incident_alarms_pair"),
    )
    op.create_index("ix_incident_alarms_alarm_id", "incident_alarms", ["alarm_id"])


def downgrade() -> None:
    """Restore the pre-6.9 alarm shape.

    Every added column, index, and constraint is removed and both new tables are
    dropped. No row is deleted, so the pre-migration row count is restored and
    ``uq_alarm_telemetry_rule`` keeps holding. The ``CLEARED`` relabelling applied
    by the duplicate backfill is not reversed, because the original status of a
    consolidated row cannot be reconstructed. While the revision is applied the
    affected rows remain identifiable by
    ``clear_reason = 'SUPERSEDED_ON_MIGRATION_20260923_07'``; note that a
    downgrade also removes the ``clear_reason`` column itself, so a subsequent
    re-upgrade cannot restore the marker and the relabelled rows stop being
    distinguishable from organically cleared rows.
    """

    op.drop_index("ix_incident_alarms_alarm_id", table_name="incident_alarms")
    op.drop_table("incident_alarms")

    op.drop_index("ix_alarms_open_status_device", table_name="alarms")
    op.drop_index("uq_alarms_open_device_rule", table_name="alarms")
    op.drop_constraint("ck_alarms_status", "alarms", type_="check")
    op.drop_constraint("ck_alarms_occurrence_count", "alarms", type_="check")

    op.drop_column("alarms", "last_triggered_at")
    op.drop_column("alarms", "occurrence_count")
    op.drop_column("alarms", "clear_reason")
    op.drop_column("alarms", "acknowledged_by")
    op.drop_column("alarms", "acknowledged_at")

    op.drop_index("ix_alarm_rules_enabled_signal", table_name="alarm_rules")
    op.drop_table("alarm_rules")
