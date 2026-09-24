"""Alarm instance persistence queries.

Phase 6.9 promoted ``alarms`` from a per-sample rule trigger log to an active
condition instance registry, so this repository gained open-instance lookup and
windowed correlation queries. ``create`` and ``list`` keep their original
position and behaviour, so the existing read path is unchanged.

The open-instance predicate is written as ``status != 'CLEARED'`` rather than as
a list membership test, so it matches the predicate of the partial unique index
``uq_alarms_open_device_rule`` and the planner can use that index.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alarm

#: Still-open instance predicate. Matches the partial index predicate verbatim.
OPEN_INSTANCE_PREDICATE: ColumnElement[bool] = Alarm.status != "CLEARED"

#: An alarm's most recent activity. A condition that opened an hour ago and is
#: still breaching belongs to the current correlation window, so correlation
#: uses the latest trigger rather than the first one.
ACTIVITY_AT = func.coalesce(Alarm.last_triggered_at, Alarm.started_at)


class AlarmRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        device_id: str,
        telemetry_id: UUID | None,
        rule_id: str,
        severity: str,
        message: str,
        started_at: datetime | None = None,
        occurrence_count: int = 1,
    ) -> Alarm:
        alarm = Alarm(
            device_id=device_id,
            telemetry_id=telemetry_id,
            rule_id=rule_id,
            severity=severity,
            message=message,
            status="ACTIVE",
            started_at=started_at,
            last_triggered_at=started_at,
            occurrence_count=occurrence_count,
        )
        self.session.add(alarm)
        await self.session.flush()
        return alarm

    async def get(self, alarm_id: UUID) -> Alarm | None:
        return await self.session.get(Alarm, alarm_id)

    async def find_open(self, device_id: str, rule_id: str) -> Alarm | None:
        """Return the open instance for a device and rule, if one exists.

        At most one row can match, because ``uq_alarms_open_device_rule`` is a
        partial unique index over this exact predicate. The ordering is a
        defensive tiebreak that cannot currently be reached.
        """

        return cast(
            Alarm | None,
            await self.session.scalar(
                select(Alarm)
                .where(Alarm.device_id == device_id)
                .where(Alarm.rule_id == rule_id)
                .where(OPEN_INSTANCE_PREDICATE)
                .order_by(Alarm.started_at.asc())
                .limit(1)
            ),
        )

    async def list_instances(
        self,
        device_id: str | None,
        limit: int,
        *,
        status: str | None = None,
        severity: str | None = None,
        rule_id: str | None = None,
        since: datetime | None = None,
        open_only: bool = False,
        device_ids: frozenset[str] | None = None,
    ) -> list[Alarm]:
        """List alarm instances, newest first.

        The secondary key on ``id`` makes the order total, so pagination and
        tests cannot observe an arbitrary order when two instances share a
        ``started_at``.

        ``device_ids`` is the Phase 6.13-B scope filter: the caller's reachable
        device set, applied as a membership predicate. ``None`` means no
        restriction; the single ``device_id`` argument, when given, still wins
        for an exact lookup.
        """

        query = select(Alarm)
        if device_id is not None:
            query = query.where(Alarm.device_id == device_id)
        elif device_ids is not None:
            query = query.where(Alarm.device_id.in_(device_ids))
        if status is not None:
            query = query.where(Alarm.status == status)
        elif open_only:
            query = query.where(OPEN_INSTANCE_PREDICATE)
        if severity is not None:
            query = query.where(Alarm.severity == severity)
        if rule_id is not None:
            query = query.where(Alarm.rule_id == rule_id)
        if since is not None:
            query = query.where(since <= ACTIVITY_AT)
        rows = await self.session.scalars(
            query.order_by(Alarm.started_at.desc(), Alarm.id.desc()).limit(limit)
        )
        return list(rows)

    async def related(
        self,
        *,
        device_id: str,
        window_start: datetime,
        rule_id: str | None = None,
        include_open: bool = True,
        limit: int = 50,
    ) -> list[Alarm]:
        """Return alarm instances related to a device inside a time window.

        An open instance always qualifies, however long it has been open, because
        an unacknowledged condition is related by definition. A cleared instance
        qualifies only when its last activity falls inside the window.
        """

        predicates: list[ColumnElement[bool]] = [window_start <= ACTIVITY_AT]
        if include_open:
            predicates.append(OPEN_INSTANCE_PREDICATE)
        query = select(Alarm).where(Alarm.device_id == device_id).where(or_(*predicates))
        if rule_id is not None:
            query = query.where(Alarm.rule_id == rule_id)
        rows = await self.session.scalars(
            query.order_by(ACTIVITY_AT.desc(), Alarm.id.desc()).limit(limit)
        )
        return list(rows)
