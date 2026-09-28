"""Enterprise governance persistence models (Phase 6.13-C).

Two tables, both additive, neither a second audit, device, or asset system:

``governance_policies``
    Conditional DENY rules evaluated by the Policy Engine on every governed
    permission decision. RBAC answers "does this role hold this permission";
    a governance policy answers "does a rule above RBAC refuse it right now".
    A policy never grants: it can only refuse, so removing the governance
    layer always leaves exactly the RBAC answer.

``change_records``
    The change-management ledger. One row per intended or performed change,
    with a lifecycle state machine (DRAFT → SCHEDULED → IN_PROGRESS →
    COMPLETED, cancelled from DRAFT or SCHEDULED). The ledger records changes;
    it does not perform them, approve them, or touch the Workflow / Approval
    state machines. ``requested_by_user_id`` follows the audit-trail principle:
    a bare reference, no foreign key, so deleting an identity can never erase
    who asked for a change.

Condition payloads (``governance_policies.conditions``) are JSONB and are
validated by the API before they are stored; the Policy Engine treats an
unknown condition kind as a match-failure (the policy is inert), never as a
crash and never as a silent allow. The supported kinds live in
:mod:`app.security.policy_engine`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base
from app.security.models import SecurityTimestampMixin


class PolicyEffect(StrEnum):
    """What a governance policy does when its conditions match."""

    DENY = "DENY"


class ChangeStatus(StrEnum):
    """The change-record lifecycle."""

    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ChangeRisk(StrEnum):
    """The declared risk of a change; the dashboard aggregates by it."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ChangeType(StrEnum):
    """The kind of object the change concerns. Free of workflow semantics."""

    CONFIGURATION = "CONFIGURATION"
    HARDWARE = "HARDWARE"
    PROCEDURE = "PROCEDURE"


#: Legal transitions of the change-record state machine. Anything else is a
#: 409 at the API boundary, so a record can never skip its execution window
#: or resurrect after completion.
CHANGE_TRANSITIONS: dict[ChangeStatus, frozenset[ChangeStatus]] = {
    ChangeStatus.DRAFT: frozenset({ChangeStatus.SCHEDULED, ChangeStatus.CANCELLED}),
    ChangeStatus.SCHEDULED: frozenset({ChangeStatus.IN_PROGRESS, ChangeStatus.CANCELLED}),
    ChangeStatus.IN_PROGRESS: frozenset({ChangeStatus.COMPLETED, ChangeStatus.CANCELLED}),
    ChangeStatus.COMPLETED: frozenset(),
    ChangeStatus.CANCELLED: frozenset(),
}


def _change_status_values() -> str:
    return ", ".join(f"'{status.value}'" for status in ChangeStatus)


def _change_risk_values() -> str:
    return ", ".join(f"'{risk.value}'" for risk in ChangeRisk)


def _change_type_values() -> str:
    return ", ".join(f"'{kind.value}'" for kind in ChangeType)


class GovernancePolicy(SecurityTimestampMixin, Base):
    """One conditional DENY rule of the governance Policy Engine."""

    __tablename__ = "governance_policies"
    __table_args__ = (
        CheckConstraint("effect IN ('DENY')", name="ck_governance_policies_effect"),
        Index("ix_governance_policies_enabled", "enabled"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    effect: Mapped[str] = mapped_column(String(10), nullable=False, default=PolicyEffect.DENY.value)
    permission: Mapped[str] = mapped_column(String(100), nullable=False)
    conditions: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)


class ChangeRecord(SecurityTimestampMixin, Base):
    """One entry of the change-management ledger."""

    __tablename__ = "change_records"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_change_status_values()})",
            name="ck_change_records_status",
        ),
        CheckConstraint(
            f"risk_level IN ({_change_risk_values()})",
            name="ck_change_records_risk",
        ),
        CheckConstraint(
            f"change_type IN ({_change_type_values()})",
            name="ck_change_records_type",
        ),
        CheckConstraint(
            "scheduled_end IS NULL OR scheduled_start IS NULL OR scheduled_end > scheduled_start",
            name="ck_change_records_window",
        ),
        Index("ix_change_records_status", "status"),
        Index("ix_change_records_window", "scheduled_start", "scheduled_end"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, server_default="")
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ChangeStatus.DRAFT.value
    )
    resource_type: Mapped[str | None] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(String(200))
    requested_by_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    requested_by_name: Mapped[str | None] = mapped_column(String(100))
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
