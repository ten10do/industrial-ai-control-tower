"""Incident lifecycle, correlation, and context services.

Three services share one bounded context but not one responsibility.

``IncidentLifecycleService`` owns incident state. It performs the operator
commands this phase introduces, each a guarded move through the single
transition table in ``app/incidents/states.py``.

``IncidentCorrelationService`` owns the deterministic merge of alarm instances
into incidents: same device, live incident, alarm activity inside the window
means attach; anything else opens a new incident. The strategy is deliberately
not clever. No clustering, no embeddings, no model calls, so the outcome for a
given set of rows is reproducible.

``IncidentContextService`` builds the read-only context bundle (alarms,
diagnosis, device, asset, audit timeline) that the detail endpoint exposes and
that a later agent-facing phase will consume.

Auditing policy matches the alarm services: state changes write one
``audit_events`` row each with ``resource`` set to the incident id, so an
incident's timeline is reconstructable from audit alone. Attaching an alarm is
a state change and is audited; the idempotent re-attach that changes nothing is
not.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import trace_id_context
from app.incidents.contracts import (
    AlarmRead,
    AssetContextRead,
    AuditEntryRead,
    DeviceContextRead,
    DiagnosisContextRead,
    IncidentContextRead,
    IncidentLifecycleRead,
)
from app.incidents.errors import AlarmLifecycleError
from app.incidents.models import IncidentAlarm
from app.incidents.states import (
    SEVERITY_ORDER,
    AlarmSeverity,
    IncidentStatus,
    describe_incident_transitions,
    is_incident_transition_allowed,
)
from app.infrastructure.database.base import utc_now
from app.models import Alarm, AssetNode, AuditEvent, Device, Diagnosis, Incident
from app.repositories.audit import AuditRepository
from app.repositories.incident import IncidentRepository
from app.repositories.incident_alarm import IncidentAlarmRepository

logger = logging.getLogger(__name__)

DEFAULT_ACTOR = "backend"

#: Correlation strategy v1: alarms on one device within this window attach to
#: the device's live incident. Ten minutes, fixed, deterministic.
DEFAULT_CORRELATION_WINDOW_SECONDS = 600

#: Deterministic severity-to-priority mapping for engine-created incidents.
SEVERITY_PRIORITY: dict[str, str] = {
    "CRITICAL": "URGENT",
    "MAJOR": "HIGH",
    "WARNING": "MEDIUM",
    "MINOR": "LOW",
    "INFO": "LOW",
}


class IncidentStateError(AlarmLifecycleError):
    """The requested incident status move is not legal."""

    code = "INCIDENT_STATE_INVALID"
    status_code = 409


class IncidentNotFoundError(AlarmLifecycleError):
    """The requested incident does not exist."""

    code = "INCIDENT_NOT_FOUND"
    status_code = 404


class AlarmIncidentMismatchError(AlarmLifecycleError):
    """An alarm cannot attach to an incident on another device."""

    code = "ALARM_INCIDENT_DEVICE_MISMATCH"
    status_code = 409


def alarm_activity_at(alarm: Alarm) -> datetime:
    """Return an alarm's most recent activity instant."""

    return alarm.last_triggered_at or alarm.started_at


def severity_to_priority(severity: str | None) -> str:
    """Map a severity to a deterministic scheduling priority."""

    return SEVERITY_PRIORITY.get(severity or "", "MEDIUM")


class IncidentLifecycleService:
    """Owns incident state and the operator commands that move it."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.incidents = IncidentRepository(session)
        self.audit = AuditRepository(session)

    async def acknowledge_incident(
        self,
        incident_id: UUID,
        *,
        actor: str = DEFAULT_ACTOR,
        note: str | None = None,
    ) -> Incident:
        """OPEN -> ACKNOWLEDGED. Records who acknowledged, when, and why."""

        incident = await self._require_incident(incident_id)
        self._require_transition(incident, IncidentStatus.ACKNOWLEDGED)
        incident.status = IncidentStatus.ACKNOWLEDGED.value
        incident.acknowledged_at = utc_now()
        incident.acknowledged_by = actor
        await self.session.flush()
        self._audit(
            action="INCIDENT_ACKNOWLEDGED",
            incident_id=incident.id,
            actor=actor,
            details={"previous_status": IncidentStatus.OPEN.value, "note": note},
        )
        await self.session.commit()
        return incident

    async def start_investigation(
        self, incident_id: UUID, *, actor: str = DEFAULT_ACTOR
    ) -> Incident:
        """ACKNOWLEDGED -> INVESTIGATING, the only exit of REOPENED."""

        incident = await self._require_incident(incident_id)
        self._require_transition(incident, IncidentStatus.INVESTIGATING)
        previous = self._status_of(incident)
        incident.status = IncidentStatus.INVESTIGATING.value
        await self.session.flush()
        self._audit(
            action="INCIDENT_INVESTIGATION_STARTED",
            incident_id=incident.id,
            actor=actor,
            details={"previous_status": previous.value},
        )
        await self.session.commit()
        return incident

    async def resolve_incident(self, incident_id: UUID, *, actor: str = DEFAULT_ACTOR) -> Incident:
        """MITIGATED -> RESOLVED."""

        incident = await self._require_incident(incident_id)
        self._require_transition(incident, IncidentStatus.RESOLVED)
        incident.status = IncidentStatus.RESOLVED.value
        incident.resolved_at = utc_now()
        await self.session.flush()
        self._audit(
            action="INCIDENT_RESOLVED",
            incident_id=incident.id,
            actor=actor,
            details={},
        )
        await self.session.commit()
        return incident

    async def close_incident(self, incident_id: UUID, *, actor: str = DEFAULT_ACTOR) -> Incident:
        """RESOLVED -> CLOSED."""

        incident = await self._require_incident(incident_id)
        self._require_transition(incident, IncidentStatus.CLOSED)
        incident.status = IncidentStatus.CLOSED.value
        incident.closed_at = utc_now()
        await self.session.flush()
        self._audit(
            action="INCIDENT_CLOSED",
            incident_id=incident.id,
            actor=actor,
            details={},
        )
        await self.session.commit()
        return incident

    async def reopen_incident(self, incident_id: UUID, *, actor: str = DEFAULT_ACTOR) -> Incident:
        """CLOSED -> REOPENED. Investigation restarts from there."""

        incident = await self._require_incident(incident_id)
        self._require_transition(incident, IncidentStatus.REOPENED)
        incident.status = IncidentStatus.REOPENED.value
        incident.closed_at = None
        incident.resolved_at = None
        await self.session.flush()
        self._audit(
            action="INCIDENT_REOPENED",
            incident_id=incident.id,
            actor=actor,
            details={"previous_status": IncidentStatus.CLOSED.value},
        )
        await self.session.commit()
        return incident

    async def _require_incident(self, incident_id: UUID) -> Incident:
        incident = await self.incidents.get(incident_id)
        if incident is None:
            raise IncidentNotFoundError(f"incident {incident_id} was not found")
        return incident

    @staticmethod
    def _status_of(incident: Incident) -> IncidentStatus:
        try:
            return IncidentStatus(incident.status)
        except ValueError as exc:
            raise IncidentStateError(
                f"incident {incident.id} carries an unrecognised status",
                {"incident_id": str(incident.id), "current_status": incident.status},
            ) from exc

    def _require_transition(self, incident: Incident, target: IncidentStatus) -> None:
        current = self._status_of(incident)
        if is_incident_transition_allowed(current, target):
            return
        raise IncidentStateError(
            f"incident is {current.value}; {target.value} is not a legal next status",
            {
                "incident_id": str(incident.id),
                "current_status": current.value,
                "target_status": target.value,
                "allowed": describe_incident_transitions(current),
            },
        )

    def _audit(
        self, *, action: str, incident_id: UUID, actor: str, details: dict[str, Any]
    ) -> None:
        self.audit.add(
            trace_id=trace_id_context.get(),
            actor=actor,
            action=action,
            resource=str(incident_id),
            status="SUCCESS",
            details=details,
        )


class IncidentCorrelationService:
    """Merges alarm instances into incidents, deterministically."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.incidents = IncidentRepository(session)
        self.links = IncidentAlarmRepository(session)
        self.audit = AuditRepository(session)

    async def correlate_alarm(
        self,
        alarm: Alarm,
        *,
        window_seconds: int = DEFAULT_CORRELATION_WINDOW_SECONDS,
        actor: str = DEFAULT_ACTOR,
    ) -> tuple[Incident, bool]:
        """Return the incident ``alarm`` belongs to, creating one if needed.

        Strategy v1 is device plus time window. If the device has a live
        incident whose last alarm activity is within ``window_seconds`` of this
        alarm's activity, the alarm attaches to it. Otherwise a new incident
        opens and absorbs the alarm. The window is anchored on incident
        evidence, not on wall clock, so replaying the same rows yields the same
        incidents.
        """

        incident = await self.incidents.find_open_for_device(alarm.device_id)
        if incident is not None and self._within_window(incident, alarm, window_seconds):
            await self.attach_alarm_to_incident(incident, alarm, actor=actor)
            return incident, False

        incident = await self._create_incident_for(alarm, actor=actor)
        await self.attach_alarm_to_incident(incident, alarm, actor=actor)
        return incident, True

    async def attach_alarm_to_incident(
        self,
        incident: Incident,
        alarm: Alarm,
        *,
        actor: str = DEFAULT_ACTOR,
    ) -> bool:
        """Link one alarm to one incident, idempotently.

        Repeating the call for the same pair leaves exactly one
        ``incident_alarms`` row and writes no second audit record. The first
        successful link updates the incident's correlation anchor and raises its
        severity to at least the alarm's.
        """

        if incident.device_id is not None and alarm.device_id != incident.device_id:
            raise AlarmIncidentMismatchError(
                "alarm device does not match the incident device",
                {"alarm_device": alarm.device_id, "incident_device": incident.device_id},
            )
        link = await self.links.link(incident.id, alarm.id)
        if link is None:
            return False
        self._absorb_alarm(incident, alarm)
        await self.session.flush()
        self.audit.add(
            trace_id=trace_id_context.get(),
            actor=actor,
            action="INCIDENT_ALARM_ATTACHED",
            resource=str(incident.id),
            status="SUCCESS",
            details={
                "alarm_id": str(alarm.id),
                "rule_id": alarm.rule_id,
                "severity": alarm.severity,
            },
        )
        return True

    @staticmethod
    def _within_window(incident: Incident, alarm: Alarm, window_seconds: int) -> bool:
        anchor = incident.last_alarm_at or incident.created_at
        if anchor is None:
            return False
        activity = alarm_activity_at(alarm)
        return bool(anchor <= activity <= anchor + timedelta(seconds=window_seconds))

    def _absorb_alarm(self, incident: Incident, alarm: Alarm) -> None:
        activity = alarm_activity_at(alarm)
        if incident.last_alarm_at is None or activity > incident.last_alarm_at:
            incident.last_alarm_at = activity
        if self._severity_rank(alarm.severity) > self._severity_rank(incident.severity):
            incident.severity = alarm.severity
            incident.priority = severity_to_priority(alarm.severity)

    @staticmethod
    def _severity_rank(severity: str | None) -> int:
        if severity is None:
            return -1
        try:
            return SEVERITY_ORDER[AlarmSeverity(severity)]
        except ValueError:
            return -1

    async def _create_incident_for(self, alarm: Alarm, *, actor: str) -> Incident:
        incident = Incident(
            device_id=alarm.device_id,
            title=f"{alarm.device_id} correlated alarm condition",
            description=(
                "Opened by deterministic correlation strategy v1 (device plus "
                f"{DEFAULT_CORRELATION_WINDOW_SECONDS}-second window): alarms on "
                "this device inside the window attach to this incident."
            ),
            status=IncidentStatus.OPEN.value,
            severity=alarm.severity,
            priority=severity_to_priority(alarm.severity),
            last_alarm_at=alarm_activity_at(alarm),
        )
        self.session.add(incident)
        await self.session.flush()
        self.audit.add(
            trace_id=trace_id_context.get(),
            actor=actor,
            action="INCIDENT_CREATED",
            resource=str(incident.id),
            status="SUCCESS",
            details={
                "strategy": "device_window_v1",
                "origin_alarm_id": str(alarm.id),
                "origin_rule_id": alarm.rule_id,
                "severity": alarm.severity,
            },
        )
        return incident


class IncidentContextService:
    """Builds the read-only context bundle around one incident."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_incident(self, incident_id: UUID) -> Incident:
        incident = await self.session.get(Incident, incident_id)
        if incident is None:
            raise IncidentNotFoundError(f"incident {incident_id} was not found")
        return incident

    async def linked_alarms(self, incident_id: UUID) -> list[Alarm]:
        """Return the incident's alarms, most recent activity first."""

        rows = await self.session.scalars(
            select(Alarm)
            .join(IncidentAlarm, IncidentAlarm.alarm_id == Alarm.id)
            .where(IncidentAlarm.incident_id == incident_id)
            .order_by(Alarm.started_at.desc(), Alarm.id.desc())
        )
        return list(rows)

    async def latest_diagnosis(self, incident_id: UUID) -> Diagnosis | None:
        """Return the newest diagnosis associated through ``diagnoses.incident_id``.

        The diagnosis association deliberately stays on the existing foreign
        key. An incident can accumulate several diagnoses across its life (a
        reopened investigation produces another), and the one-to-many edge is
        already modelled from the diagnosis side, so no second link is needed.
        """

        return cast(
            Diagnosis | None,
            await self.session.scalar(
                select(Diagnosis)
                .where(Diagnosis.incident_id == incident_id)
                .order_by(Diagnosis.created_at.desc())
                .limit(1)
            ),
        )

    async def device_with_asset(self, incident: Incident) -> tuple[Device | None, AssetNode | None]:
        if incident.device_id is None:
            return None, None
        device = await self.session.scalar(
            select(Device).where(Device.device_id == incident.device_id)
        )
        if device is None or device.asset_node_id is None:
            return device, None
        asset = await self.session.get(AssetNode, device.asset_node_id)
        return device, asset

    async def audit_timeline(self, incident_id: UUID) -> list[AuditEvent]:
        """Return every incident-scoped audit record, oldest first."""

        rows = await self.session.scalars(
            select(AuditEvent)
            .where(AuditEvent.resource == str(incident_id))
            .order_by(AuditEvent.timestamp.asc(), AuditEvent.id.asc())
        )
        return list(rows)

    async def build_context(self, incident_id: UUID) -> IncidentContextRead:
        """Assemble the full read-only context bundle for one incident."""

        incident = await self.get_incident(incident_id)
        alarms = await self.linked_alarms(incident_id)
        diagnosis = await self.latest_diagnosis(incident_id)
        device, asset = await self.device_with_asset(incident)
        timeline = await self.audit_timeline(incident_id)
        return IncidentContextRead(
            incident=IncidentLifecycleRead.model_validate(incident),
            alarms=[AlarmRead.model_validate(alarm) for alarm in alarms],
            device=DeviceContextRead.model_validate(device) if device else None,
            asset=AssetContextRead.model_validate(asset) if asset else None,
            diagnosis=DiagnosisContextRead.model_validate(diagnosis) if diagnosis else None,
            audit=[AuditEntryRead.model_validate(entry) for entry in timeline],
        )


__all__ = [
    "DEFAULT_CORRELATION_WINDOW_SECONDS",
    "AlarmIncidentMismatchError",
    "IncidentContextService",
    "IncidentCorrelationService",
    "IncidentLifecycleService",
    "IncidentNotFoundError",
    "IncidentStateError",
    "alarm_activity_at",
    "severity_to_priority",
]
