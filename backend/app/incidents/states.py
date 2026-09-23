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


__all__ = [
    "ALARM_TRANSITIONS",
    "OPEN_ALARM_STATUSES",
    "PRIORITY_ORDER",
    "SEVERITY_ORDER",
    "AlarmPriority",
    "AlarmSeverity",
    "AlarmStatus",
    "as_alarm_status",
    "describe_alarm_transitions",
    "is_alarm_transition_allowed",
    "open_alarm_status_values",
    "severity_at_least",
]
