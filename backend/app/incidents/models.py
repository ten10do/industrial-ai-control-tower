"""Phase 6.9 persistence models for the alarm lifecycle and incident linkage.

Two tables are added. Neither introduces a second device identity, a second
incident, or a second diagnosis. Device identity remains ``devices.device_id``
and incident identity remains ``incidents.id``.

* ``alarm_rules`` promotes the two hardcoded thresholds that used to live inside
  :meth:`app.services.telemetry.TelemetryService._apply_alarm_rules` into
  declarative data. A rule evaluates one canonical signal against one threshold
  and assigns a severity and a priority. It never controls a device and it never
  calls a model, so rule evaluation cannot actuate anything.
* ``incident_alarms`` records which alarm instances contributed to which
  incident. Phase 6.9-A creates the relation and the lookup that fills it. It
  deliberately does not create incidents, so no automatic alarm to incident path
  exists yet.

The columns added to the existing ``alarms`` table live on the ``Alarm`` model in
:mod:`app.models.entities`, because that table predates this package. ``alarms``
keeps every historical row and gains an open-instance invariant enforced by a
partial unique index rather than by application code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base, utc_now

#: Comparison operators a rule may use. Kept small on purpose: every added
#: operator is another branch the evaluator must be exhaustively tested against.
RULE_OPERATORS: tuple[str, ...] = ("GT", "GTE", "LT", "LTE", "EQ", "NE")

#: Canonical signal names a rule may reference, mirroring
#: ``app.gateway.models.CANONICAL_SIGNAL_FIELDS``. The gateway names the signal
#: without its unit suffix and the telemetry contract names the column with it,
#: so the mapping between the two lives in :mod:`app.incidents.rules`.
RULE_SIGNAL_NAMES: tuple[str, ...] = (
    "temperature",
    "bearing_temperature",
    "vibration",
    "current",
    "voltage",
    "rpm",
    "load",
    "power",
)

RULE_SEVERITIES: tuple[str, ...] = ("INFO", "MINOR", "WARNING", "MAJOR", "CRITICAL")

RULE_PRIORITIES: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "URGENT")


def _sql_in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class AlarmRule(Base):
    """One declarative alarm rule.

    ``id`` is the durable natural key and it is what ``alarms.rule_id`` has
    always stored, so historical alarm rows resolve to a rule without a mapping
    step. There is deliberately no foreign key from ``alarms.rule_id`` to this
    table: a cleared historical alarm must stay explainable even after its rule
    is removed, and either restrictive or nullifying referential action would
    break that.
    """

    __tablename__ = "alarm_rules"
    __table_args__ = (
        CheckConstraint(
            f"signal_name IN ({_sql_in_list(RULE_SIGNAL_NAMES)})",
            name="ck_alarm_rules_signal_name",
        ),
        CheckConstraint(
            f"operator IN ({_sql_in_list(RULE_OPERATORS)})",
            name="ck_alarm_rules_operator",
        ),
        CheckConstraint(
            f"severity IN ({_sql_in_list(RULE_SEVERITIES)})",
            name="ck_alarm_rules_severity",
        ),
        CheckConstraint(
            f"priority IN ({_sql_in_list(RULE_PRIORITIES)})",
            name="ck_alarm_rules_priority",
        ),
        Index("ix_alarm_rules_enabled_signal", "enabled", "signal_name"),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    device_type: Mapped[str | None] = mapped_column(String(50))
    signal_name: Mapped[str] = mapped_column(String(50), nullable=False)
    operator: Mapped[str] = mapped_column(String(10), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class IncidentAlarm(Base):
    """Link between one incident and one alarm instance.

    The many-to-many shape is the honest one. An alarm instance is cleared and a
    new instance opens when the same condition recurs on the same device, so a
    single ``incident_id`` column on ``alarms`` would have to be rewritten on
    every recurrence and would erase which incident an earlier occurrence
    belonged to.
    """

    __tablename__ = "incident_alarms"
    __table_args__ = (
        UniqueConstraint("incident_id", "alarm_id", name="uq_incident_alarms_pair"),
        Index("ix_incident_alarms_alarm_id", "alarm_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    incident_id: Mapped[UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE", name="fk_incident_alarms_incident_id"),
        nullable=False,
    )
    alarm_id: Mapped[UUID] = mapped_column(
        ForeignKey("alarms.id", ondelete="CASCADE", name="fk_incident_alarms_alarm_id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


def rule_snapshot(rule: AlarmRule) -> dict[str, Any]:
    """Return the rule fields worth copying into an audit record."""

    return {
        "rule_id": rule.id,
        "name": rule.name,
        "signal_name": rule.signal_name,
        "operator": rule.operator,
        "threshold": rule.threshold,
        "severity": rule.severity,
        "priority": rule.priority,
        "device_type": rule.device_type,
    }


__all__ = [
    "RULE_OPERATORS",
    "RULE_PRIORITIES",
    "RULE_SEVERITIES",
    "RULE_SIGNAL_NAMES",
    "AlarmRule",
    "IncidentAlarm",
    "rule_snapshot",
]
