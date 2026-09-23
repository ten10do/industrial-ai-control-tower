"""Incident correlation foundation.

Phase 6.9-A stops deliberately short of correlation behaviour. It provides the
lookup that a later stage needs and nothing that acts on the result:

* ``find_related_alarm`` answers "does an alarm instance already relate to this
  device and rule".
* ``find_related_alarms`` answers the wider question "which instances relate to
  this device inside this window", which is the evidence set an incident will
  eventually be assembled from.

There is no automatic alarm to incident path here. Nothing in this module creates
an incident, mutates an incident, or links an alarm to one.

An open instance always qualifies however long it has been open, because an
unacknowledged condition is related by definition. A cleared instance qualifies
only when its last activity falls inside the window. Using the latest trigger
rather than the first one is what makes a condition that opened an hour ago and
is still breaching count as related now.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents.errors import AlarmLifecycleError
from app.infrastructure.database.base import utc_now
from app.models import Alarm
from app.repositories.alarm import AlarmRepository

DEFAULT_WINDOW_SECONDS = 300
MAX_WINDOW_SECONDS = 86_400


class CorrelationWindowError(AlarmLifecycleError):
    """The requested correlation window is not usable."""

    code = "CORRELATION_WINDOW_INVALID"
    status_code = 422


def resolve_reference(reference: datetime | None) -> datetime:
    """Return an aware reference instant, refusing a naive one.

    A naive timestamp would be interpreted in the server's local zone and could
    silently shift a correlation window by hours. Refusing is safer than guessing.
    """

    if reference is None:
        return utc_now()
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise CorrelationWindowError("the correlation reference must be timezone-aware")
    return reference


def window_start(reference: datetime | None, window_seconds: int) -> datetime:
    """Return the inclusive start of the correlation window."""

    if window_seconds < 1 or window_seconds > MAX_WINDOW_SECONDS:
        raise CorrelationWindowError(
            f"window_seconds must be between 1 and {MAX_WINDOW_SECONDS}",
            {"window_seconds": window_seconds},
        )
    return resolve_reference(reference) - timedelta(seconds=window_seconds)


async def find_related_alarms(
    session: AsyncSession,
    *,
    device_id: str,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    reference: datetime | None = None,
    rule_id: str | None = None,
    include_open: bool = True,
    limit: int = 50,
) -> list[Alarm]:
    """Return alarm instances related to a device inside a window.

    ``include_open=False`` restricts the result to instances whose last activity
    falls inside the window, which is how a caller asks "what happened recently"
    rather than "what is still live".
    """

    start = window_start(reference, window_seconds)
    return await AlarmRepository(session).related(
        device_id=device_id,
        window_start=start,
        rule_id=rule_id,
        include_open=include_open,
        limit=limit,
    )


async def find_related_alarm(
    session: AsyncSession,
    *,
    device_id: str,
    rule_id: str,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    reference: datetime | None = None,
) -> Alarm | None:
    """Return the alarm instance that already relates to a device and rule.

    An open instance wins over any cleared one, and an open instance is returned
    regardless of age. Only when no instance is open does the window apply, and
    then the most recently active cleared instance wins.
    """

    repository = AlarmRepository(session)
    open_instance = await repository.find_open(device_id, rule_id)
    if open_instance is not None:
        return open_instance
    start = window_start(reference, window_seconds)
    cleared = await repository.related(
        device_id=device_id,
        window_start=start,
        rule_id=rule_id,
        include_open=False,
        limit=1,
    )
    return cleared[0] if cleared else None


__all__ = [
    "DEFAULT_WINDOW_SECONDS",
    "MAX_WINDOW_SECONDS",
    "CorrelationWindowError",
    "find_related_alarm",
    "find_related_alarms",
    "resolve_reference",
    "window_start",
]
