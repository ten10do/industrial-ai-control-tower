"""Incident instance persistence queries.

Phase 6.9-B gives incidents a lifecycle and a correlation engine, so this
repository owns the open-incident lookup the engine depends on and the filtered
listing the read API exposes. The open predicate matches
``OPEN_INCIDENT_STATUSES`` in ``app/incidents/states.py``; statuses are stored
as plain strings, so the SQL comparison uses an IN list over those values.

The correlation anchor is ``last_alarm_at`` falling back to ``created_at``: an
incident that has just been created with its first alarm already carries the
anchor, and a manually created incident with no alarms yet anchors at creation.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents.states import open_incident_status_values
from app.models import Incident

#: Still-live incident predicate, expressed as an IN list so the planner can use
#: ``ix_incidents_device_status``.
OPEN_INCIDENT_PREDICATE: ColumnElement[bool] = Incident.status.in_(open_incident_status_values())

#: An incident's most recent alarm evidence.
ACTIVITY_AT = func.coalesce(Incident.last_alarm_at, Incident.created_at)


class IncidentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, incident_id: UUID) -> Incident | None:
        return await self.session.get(Incident, incident_id)

    async def find_open_for_device(self, device_id: str) -> Incident | None:
        """Return the live incident a new alarm on ``device_id`` would join.

        At most one incident per device is live by correlation design, but the
        database does not enforce that (manual creation and the workflow path
        also create incidents), so the most recently active one wins.
        """

        return cast(
            Incident | None,
            await self.session.scalar(
                select(Incident)
                .where(Incident.device_id == device_id)
                .where(OPEN_INCIDENT_PREDICATE)
                .order_by(ACTIVITY_AT.desc(), Incident.id.desc())
                .limit(1)
            ),
        )

    async def list_instances(
        self,
        limit: int,
        *,
        status: str | None = None,
        severity: str | None = None,
        device_id: str | None = None,
    ) -> list[Incident]:
        """List incidents, newest first, with the read API's filters."""

        query = select(Incident)
        if status is not None:
            query = query.where(Incident.status == status)
        if severity is not None:
            query = query.where(Incident.severity == severity)
        if device_id is not None:
            query = query.where(Incident.device_id == device_id)
        rows = await self.session.scalars(
            query.order_by(Incident.created_at.desc(), Incident.id.desc()).limit(limit)
        )
        return list(rows)
