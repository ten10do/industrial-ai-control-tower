"""Alarm lifecycle vocabulary and the guarded transition table.

Phase 6.9-A raises the alarm from a per-sample rule trigger record to an active
condition lifecycle instance. That promotion is only meaningful if the legal
status moves are written down once and enforced in one place, because the
failure mode it replaces is exactly four modules writing five status literals
with no guard between them.

This module holds no persistence and no I/O. It is the single authority for
three vocabularies:

* ``AlarmStatus`` is the lifecycle of one condition instance on one device.
* ``AlarmSeverity`` is technical impact, and it is ordered.
* ``AlarmPriority`` is scheduling urgency, and it is a separate axis from
  severity on purpose. A critical condition on a redundant standby machine is
  legitimately low priority, and a warning on a single point of failure is
  legitimately high priority. Collapsing the two axes destroys both statements.

Lifecycle::

    ACTIVE -> ACKNOWLEDGED -> CLEARED
       |            |
       +------------+--> CLEARED

``CLEARED`` is terminal for an instance. A recurrence opens a new instance, so
history stays attributable and ``CLEARED -> ACTIVE`` is refused rather than
silently reopening a row that an operator already closed.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class AlarmStatus(StrEnum):
    """Status of one active condition instance."""

    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLEARED = "CLEARED"


class AlarmSeverity(StrEnum):
    """Technical impact, ordered from least to most severe."""

    INFO = "INFO"
    MINOR = "MINOR"
    WARNING = "WARNING"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class AlarmPriority(StrEnum):
    """Scheduling urgency, deliberately independent of severity."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


SEVERITY_ORDER: dict[AlarmSeverity, int] = {
    AlarmSeverity.INFO: 0,
    AlarmSeverity.MINOR: 1,
    AlarmSeverity.WARNING: 2,
    AlarmSeverity.MAJOR: 3,
    AlarmSeverity.CRITICAL: 4,
}

PRIORITY_ORDER: dict[AlarmPriority, int] = {
    AlarmPriority.LOW: 0,
    AlarmPriority.MEDIUM: 1,
    AlarmPriority.HIGH: 2,
    AlarmPriority.URGENT: 3,
}

#: Statuses that still describe an open condition. The partial unique index on
#: ``alarms`` covers exactly this set, so at most one open instance can exist for
#: a given device and rule.
OPEN_ALARM_STATUSES: frozenset[AlarmStatus] = frozenset(
    {AlarmStatus.ACTIVE, AlarmStatus.ACKNOWLEDGED}
)

#: The one place a legal alarm status move is declared.
ALARM_TRANSITIONS: dict[AlarmStatus, frozenset[AlarmStatus]] = {
    AlarmStatus.ACTIVE: frozenset({AlarmStatus.ACKNOWLEDGED, AlarmStatus.CLEARED}),
    AlarmStatus.ACKNOWLEDGED: frozenset({AlarmStatus.CLEARED, AlarmStatus.ACTIVE}),
    AlarmStatus.CLEARED: frozenset(),
}


def is_alarm_transition_allowed(current: AlarmStatus, target: AlarmStatus) -> bool:
    """Return whether ``current -> target`` is a declared legal move."""

    return target in ALARM_TRANSITIONS[current]


def describe_alarm_transitions(current: AlarmStatus) -> list[str]:
    """Return the legal targets for ``current``, sorted for stable rendering."""

    return sorted(status.value for status in ALARM_TRANSITIONS[current])


def open_alarm_status_values() -> list[str]:
    """Return the open statuses as plain strings, for SQL comparisons."""

    return sorted(status.value for status in OPEN_ALARM_STATUSES)


def severity_at_least(candidate: str | None, floor: AlarmSeverity) -> bool:
    """Return whether ``candidate`` is at or above ``floor``.

    An unknown or absent candidate is treated as below every floor, so an
    unmapped label can never be mistaken for a severe one. That default is the
    safe direction: it under-promotes rather than over-promotes.
    """

    if candidate is None:
        return False
    try:
        parsed = AlarmSeverity(candidate)
    except ValueError:
        return False
    return SEVERITY_ORDER[parsed] >= SEVERITY_ORDER[floor]


def as_alarm_status(value: Any) -> AlarmStatus:
    """Coerce a stored string to ``AlarmStatus``, refusing unknown values."""

    return AlarmStatus(str(value))


class IncidentStatus(StrEnum):
    """Status of one incident.

    The vocabulary covers the operator chain this phase introduces and the three
    statuses the workflow engine already writes with raw strings
    (``UNDER_ANALYSIS``, ``ACTION_PENDING``, ``WORK_ORDER_CREATED``). Those are
    first-class members of the table rather than tolerated accidents, so the
    state graph stays complete and the workflow contract stays testable even
    though the workflow engine itself does not go through this module.
    """

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    UNDER_ANALYSIS = "UNDER_ANALYSIS"
    ACTION_PENDING = "ACTION_PENDING"
    WORK_ORDER_CREATED = "WORK_ORDER_CREATED"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    CANCELLED = "CANCELLED"


#: Statuses that still describe a live incident. The correlation engine only
#: attaches alarms to incidents in this set; a resolved, closed, or cancelled
#: incident never absorbs new evidence.
OPEN_INCIDENT_STATUSES: frozenset[IncidentStatus] = frozenset(
    {
        IncidentStatus.OPEN,
        IncidentStatus.ACKNOWLEDGED,
        IncidentStatus.INVESTIGATING,
        IncidentStatus.UNDER_ANALYSIS,
        IncidentStatus.ACTION_PENDING,
        IncidentStatus.WORK_ORDER_CREATED,
        IncidentStatus.MITIGATED,
        IncidentStatus.REOPENED,
    }
)

#: Statuses the operator chain ends at. ``CLOSED`` has exactly one exit, an
#: explicit reopen; ``CANCELLED`` is dead by decision and nothing leaves it.
TERMINAL_INCIDENT_STATUSES: frozenset[IncidentStatus] = frozenset(
    {IncidentStatus.CLOSED, IncidentStatus.CANCELLED}
)

#: The one place a legal incident status move is declared. Transitions marked as
#: workflow-owned (``UNDER_ANALYSIS``, ``ACTION_PENDING``,
#: ``WORK_ORDER_CREATED``) are written by ``workflow/service.py`` with raw
#: strings today; they are declared here so the graph is complete and the
#: contract is testable without modifying the workflow engine.
INCIDENT_TRANSITIONS: dict[IncidentStatus, frozenset[IncidentStatus]] = {
    IncidentStatus.OPEN: frozenset(
        {IncidentStatus.ACKNOWLEDGED, IncidentStatus.CANCELLED, IncidentStatus.UNDER_ANALYSIS}
    ),
    IncidentStatus.ACKNOWLEDGED: frozenset(
        {IncidentStatus.INVESTIGATING, IncidentStatus.CANCELLED, IncidentStatus.UNDER_ANALYSIS}
    ),
    IncidentStatus.INVESTIGATING: frozenset(
        {IncidentStatus.MITIGATED, IncidentStatus.UNDER_ANALYSIS}
    ),
    IncidentStatus.UNDER_ANALYSIS: frozenset(
        {IncidentStatus.ACTION_PENDING, IncidentStatus.MITIGATED}
    ),
    IncidentStatus.ACTION_PENDING: frozenset({IncidentStatus.WORK_ORDER_CREATED}),
    IncidentStatus.WORK_ORDER_CREATED: frozenset({IncidentStatus.MITIGATED}),
    IncidentStatus.MITIGATED: frozenset({IncidentStatus.RESOLVED}),
    IncidentStatus.RESOLVED: frozenset({IncidentStatus.CLOSED}),
    IncidentStatus.CLOSED: frozenset({IncidentStatus.REOPENED}),
    IncidentStatus.REOPENED: frozenset({IncidentStatus.INVESTIGATING}),
    IncidentStatus.CANCELLED: frozenset(),
}


def is_incident_transition_allowed(current: IncidentStatus, target: IncidentStatus) -> bool:
    """Return whether ``current -> target`` is a declared legal move."""

    return target in INCIDENT_TRANSITIONS[current]


def describe_incident_transitions(current: IncidentStatus) -> list[str]:
    """Return the legal targets for ``current``, sorted for stable rendering."""

    return sorted(status.value for status in INCIDENT_TRANSITIONS[current])


def open_incident_status_values() -> list[str]:
    """Return the open statuses as plain strings, for SQL comparisons."""

    return sorted(status.value for status in OPEN_INCIDENT_STATUSES)


def as_incident_status(value: Any) -> IncidentStatus:
    """Coerce a stored string to ``IncidentStatus``, refusing unknown values."""

    return IncidentStatus(str(value))


__all__ = [
    "INCIDENT_TRANSITIONS",
    "OPEN_INCIDENT_STATUSES",
    "PRIORITY_ORDER",
    "SEVERITY_ORDER",
    "TERMINAL_INCIDENT_STATUSES",
    "AlarmPriority",
    "AlarmSeverity",
    "AlarmStatus",
    "IncidentStatus",
    "as_alarm_status",
    "as_incident_status",
    "describe_alarm_transitions",
    "describe_incident_transitions",
    "is_alarm_transition_allowed",
    "is_incident_transition_allowed",
    "open_alarm_status_values",
    "open_incident_status_values",
    "severity_at_least",
]
