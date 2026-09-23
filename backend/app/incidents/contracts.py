"""Phase 6.9-A request and response contracts.

The alarm read contract moved here from ``app.schemas.alarm`` when the alarm grew
a lifecycle. It keeps every field the previous contract exposed, so the existing
read-only client sees the same shape with additive fields.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.incidents.models import (
    RULE_OPERATORS,
    RULE_PRIORITIES,
    RULE_SEVERITIES,
    RULE_SIGNAL_NAMES,
)

MAX_ALARM_NOTE = 500
MAX_ALARM_REASON = 500
MAX_RULE_ID = 100
MAX_RULE_NAME = 200
MAX_RULE_DESCRIPTION = 2_000
MAX_DEVICE_TYPE = 50


class AlarmRead(BaseModel):
    """One alarm instance.

    ``occurrence_count`` and ``last_triggered_at`` are what replaced the stream of
    duplicate rows a sustained condition used to produce. ``started_at`` stays the
    first breach, so the age of a condition is readable directly from the row.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_id: str
    telemetry_id: UUID | None
    rule_id: str
    severity: str
    status: str
    message: str
    started_at: datetime
    last_triggered_at: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    cleared_at: datetime | None = None
    clear_reason: str | None = None
    occurrence_count: int = 1

    @computed_field  # type: ignore[prop-decorator]
    @property
    def open(self) -> bool:
        """Whether this instance still describes a live condition.

        Derived rather than stored, so it can never disagree with ``status``.
        """

        return self.status != "CLEARED"


class AlarmDetailRead(AlarmRead):
    """An alarm instance plus the incidents it has been linked to.

    Incident identifiers are only resolved on the detail endpoint. Resolving them
    in the list endpoint would add a query per row for information the list view
    does not show.
    """

    incident_ids: list[UUID] = Field(default_factory=list)


class AlarmAcknowledgeRequest(BaseModel):
    """Body of an acknowledgement. The note is optional descriptive context."""

    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=MAX_ALARM_NOTE)


class AlarmClearRequest(BaseModel):
    """Body of a manual clear.

    The reason is required. Clearing is the act that removes a signal from every
    operator's view, so it has to be explainable afterwards.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=3, max_length=MAX_ALARM_REASON)


class AlarmRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    device_type: str | None
    signal_name: str
    operator: str
    threshold: float
    severity: str
    priority: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AlarmRuleCreate(BaseModel):
    """Body of a rule creation.

    A rule that is created disabled is valid. Disabling is how a rule is retired
    without deleting the history that references its identifier.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=MAX_RULE_ID)
    name: str = Field(min_length=1, max_length=MAX_RULE_NAME)
    description: str = Field(default="", max_length=MAX_RULE_DESCRIPTION)
    device_type: str | None = Field(default=None, max_length=MAX_DEVICE_TYPE)
    signal_name: str = Field(description=f"one of {', '.join(RULE_SIGNAL_NAMES)}")
    operator: str = Field(description=f"one of {', '.join(RULE_OPERATORS)}")
    threshold: float
    severity: str = Field(description=f"one of {', '.join(RULE_SEVERITIES)}")
    priority: str = Field(default="MEDIUM", description=f"one of {', '.join(RULE_PRIORITIES)}")
    enabled: bool = True


class AlarmRuleUpdate(BaseModel):
    """Body of a rule patch.

    Every field is optional and unset fields are left untouched, so a patch that
    changes only ``threshold`` cannot silently clear the rule's scope. Passing an
    explicit null for ``device_type`` is meaningful and widens the rule to all
    device types.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=MAX_RULE_NAME)
    description: str | None = Field(default=None, max_length=MAX_RULE_DESCRIPTION)
    device_type: str | None = Field(default=None, max_length=MAX_DEVICE_TYPE)
    signal_name: str | None = None
    operator: str | None = None
    threshold: float | None = None
    severity: str | None = None
    priority: str | None = None
    enabled: bool | None = None


__all__ = [
    "AlarmAcknowledgeRequest",
    "AlarmClearRequest",
    "AlarmDetailRead",
    "AlarmRead",
    "AlarmRuleCreate",
    "AlarmRuleRead",
    "AlarmRuleUpdate",
]
