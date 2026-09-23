"""Incident to alarm linkage persistence queries.

Phase 6.9-A creates this relation and the lookup that fills it. It writes no
incident, so no automatic alarm to incident path exists yet. The relation exists
so that the correlation stage can attach alarm evidence to an incident without
altering the ``alarms`` table again.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents.models import IncidentAlarm


class IncidentAlarmRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def link(self, incident_id: UUID, alarm_id: UUID) -> IncidentAlarm | None:
        """Attach an alarm to an incident, tolerating a repeat.

        Linking is idempotent. A second attempt for the same pair returns
        ``None`` and changes nothing, so a retry after a partial failure cannot
        raise and cannot create a duplicate row. The unique constraint on the
        pair is the authority; this method relies on it rather than on a
        read-then-write check that two workers could both pass.
        """

        statement = (
            insert(IncidentAlarm)
            .values(incident_id=incident_id, alarm_id=alarm_id)
            .on_conflict_do_nothing(constraint="uq_incident_alarms_pair")
            .returning(IncidentAlarm.id)
        )
        link_id = await self.session.scalar(statement)
        if link_id is None:
            return None
        return await self.session.get(IncidentAlarm, link_id)

    async def incident_ids_for_alarm(self, alarm_id: UUID) -> list[UUID]:
        rows = await self.session.scalars(
            select(IncidentAlarm.incident_id)
            .where(IncidentAlarm.alarm_id == alarm_id)
            .order_by(IncidentAlarm.created_at.asc(), IncidentAlarm.id.asc())
        )
        return list(rows)

    async def alarm_ids_for_incident(self, incident_id: UUID) -> list[UUID]:
        rows = await self.session.scalars(
            select(IncidentAlarm.alarm_id)
            .where(IncidentAlarm.incident_id == incident_id)
            .order_by(IncidentAlarm.created_at.asc(), IncidentAlarm.id.asc())
        )
        return list(rows)
