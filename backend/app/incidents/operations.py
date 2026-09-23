"""Incident Operations Center services: dashboard, metrics, workflow bridge, gate.

Phase 6.9-C adds a read-and-decide layer on top of the Phase 6.9-B lifecycle.
Three responsibilities share this module:

``IncidentOperationsService`` is read-only. It builds the dashboard (header
counters plus the incident table with bulk-resolved asset and workflow
columns), the workflow bridge answer for one incident, and the operational
metrics (MTTA, MTTR, alarm compression). It never mutates a row.

``IncidentWorkflowGate`` is the single readiness check in front of workflow
creation. It refuses incidents whose status cannot legally move to the
workflow-owned ``UNDER_ANALYSIS`` and incidents without a usable diagnosis.
The refusal is ``INCIDENT_NOT_READY`` (409) with the failing reason named, so
the Incident Center can explain itself instead of surfacing a bare error.

The gate deliberately stops at workflow creation. What happens inside the
workflow — triage, planning, safety review, the approval interrupt, and any
work order — belongs to the existing Phase 5 engine and is not re-implemented
or bypassed here.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import trace_id_context
from app.incidents.errors import AlarmLifecycleError
from app.incidents.incident_service import IncidentContextService
from app.incidents.models import IncidentAlarm
from app.incidents.states import (
    IncidentStatus,
    is_incident_transition_allowed,
    open_incident_status_values,
)
from app.models import Approval, AssetNode, Device, Diagnosis, Incident, WorkflowRun
from app.repositories.audit import AuditRepository

#: Incident statuses from which starting the decision workflow is legal. These
#: are exactly the statuses whose transition table lists ``UNDER_ANALYSIS``;
#: the gate derives the set instead of hardcoding it, so the states module
#: stays the single authority.
WORKFLOW_ENTRY_STATUSES: frozenset[IncidentStatus] = frozenset(
    status
    for status in IncidentStatus
    if is_incident_transition_allowed(status, IncidentStatus.UNDER_ANALYSIS)
)

#: Diagnosis statuses the existing workflow engine accepts. The gate pre-checks
#: the same vocabulary so an unstartable incident is refused with one clear
#: error instead of surfacing the engine's deeper 422.
WORKFLOW_READY_DIAGNOSIS_STATUSES: frozenset[str] = frozenset({"FAULT", "UNCERTAIN"})

CRITICAL_SEVERITY = "CRITICAL"


class IncidentNotReadyError(AlarmLifecycleError):
    """The incident cannot enter the decision workflow yet."""

    code = "INCIDENT_NOT_READY"
    status_code = 409


class IncidentOperationsService:
    """Read-only dashboard, bridge, and metrics queries for the Incident Center."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.context = IncidentContextService(session)

    async def dashboard(
        self,
        *,
        limit: int = 100,
        status: str | None = None,
        severity: str | None = None,
        device_id: str | None = None,
    ) -> tuple[dict[str, int], list[dict[str, object]]]:
        """Return ``(summary, rows)`` for the Incident Center.

        The summary counts are computed over the *whole* incident population,
        not just the returned page, so the header stays truthful when more
        incidents exist than the table shows. ``rows`` are the newest ``limit``
        incidents with asset names and workflow statuses resolved in bulk
        (three extra queries total, never one per row).
        """

        summary = await self._summary()
        rows = await self._rows(limit=limit, status=status, severity=severity, device_id=device_id)
        return summary, rows

    async def _summary(self) -> dict[str, int]:
        active_predicate = Incident.status.in_(open_incident_status_values())
        active = await self._count(active_predicate)
        critical = await self._count(active_predicate, Incident.severity == CRITICAL_SEVERITY)
        unacknowledged = await self._count(active_predicate, Incident.acknowledged_at.is_(None))
        return {
            "active": active,
            "critical": critical,
            "unacknowledged": unacknowledged,
        }

    async def _count(self, *criteria: object) -> int:
        statement = select(func.count()).select_from(Incident)
        if criteria:
            statement = statement.where(*criteria)  # type: ignore[arg-type]
        return int(await self.session.scalar(statement) or 0)

    async def _rows(
        self,
        *,
        limit: int,
        status: str | None,
        severity: str | None,
        device_id: str | None,
    ) -> list[dict[str, object]]:
        query = select(Incident)
        if status is not None:
            query = query.where(Incident.status == status)
        if severity is not None:
            query = query.where(Incident.severity == severity)
        if device_id is not None:
            query = query.where(Incident.device_id == device_id)
        incidents = list(
            await self.session.scalars(
                query.order_by(Incident.created_at.desc(), Incident.id.desc()).limit(limit)
            )
        )
        if not incidents:
            return []

        device_names = await self._device_asset_names(
            [incident.device_id for incident in incidents if incident.device_id is not None]
        )
        workflow_statuses = await self._latest_workflow_statuses(
            [incident.id for incident in incidents]
        )

        rows: list[dict[str, object]] = []
        for incident in incidents:
            asset_name, device_label = device_names.get(incident.device_id or "", (None, None))
            rows.append(
                {
                    "incident_id": incident.id,
                    "title": incident.title,
                    "status": incident.status,
                    "severity": incident.severity,
                    "priority": incident.priority,
                    "device_id": device_label,
                    "asset_name": asset_name,
                    "workflow_status": workflow_statuses.get(incident.id),
                    "created_at": incident.created_at,
                    "last_alarm_at": incident.last_alarm_at,
                    "resolved_at": incident.resolved_at,
                }
            )
        return rows

    async def _device_asset_names(
        self, device_ids: list[str]
    ) -> dict[str, tuple[str | None, str | None]]:
        """Return ``device_id -> (asset_name, device_id)`` in one round trip.

        The device label is echoed back so a row whose device master row was
        removed still renders (with ``None``) instead of crashing the view.
        """

        if not device_ids:
            return {}
        devices = list(
            await self.session.scalars(select(Device).where(Device.device_id.in_(device_ids)))
        )
        asset_ids = [device.asset_node_id for device in devices if device.asset_node_id is not None]
        assets: dict[UUID, str] = {}
        if asset_ids:
            for node in await self.session.scalars(
                select(AssetNode).where(AssetNode.id.in_(asset_ids))
            ):
                assets[node.id] = node.name
        return {
            device.device_id: (
                assets.get(device.asset_node_id) if device.asset_node_id is not None else None,
                device.device_id,
            )
            for device in devices
        }

    async def _latest_workflow_statuses(self, incident_ids: list[UUID]) -> dict[UUID, str]:
        """Return ``incident_id -> latest workflow status`` in one round trip."""

        if not incident_ids:
            return {}
        runs = list(
            await self.session.scalars(
                select(WorkflowRun)
                .where(WorkflowRun.incident_id.in_(incident_ids))
                .order_by(WorkflowRun.created_at.desc())
            )
        )
        latest: dict[UUID, str] = {}
        for run in runs:
            latest.setdefault(run.incident_id, run.status)
        return latest

    async def workflow_context(self, incident_id: UUID) -> dict[str, object]:
        """Return the workflow bridge answer for one incident."""

        incident = await self.context.get_incident(incident_id)
        run = await self.latest_workflow(incident.id)
        approval_required = False
        if run is not None:
            approval = await self.session.scalar(
                select(Approval).where(Approval.workflow_run_id == run.id)
            )
            approval_required = bool(
                run.status == "WAITING_APPROVAL"
                and approval is not None
                and approval.decision == "PENDING"
            )
        return {
            "incident_id": incident.id,
            "workflow_exists": run is not None,
            "workflow_run_id": run.id if run is not None else None,
            "workflow_status": run.status if run is not None else None,
            "approval_required": approval_required,
        }

    async def latest_workflow(self, incident_id: UUID) -> WorkflowRun | None:
        """Return the newest workflow run for the incident, if any."""

        return cast(
            WorkflowRun | None,
            await self.session.scalar(
                select(WorkflowRun)
                .where(WorkflowRun.incident_id == incident_id)
                .order_by(WorkflowRun.created_at.desc())
                .limit(1)
            ),
        )

    async def metrics(self) -> dict[str, float]:
        """Return MTTA, MTTR, and the alarm compression ratio.

        * MTTA — mean ``acknowledged_at - created_at`` over acknowledged incidents.
        * MTTR — mean ``resolved_at - created_at`` over resolved incidents.
        * Alarm compression — linked alarms divided by incidents. A ratio of 10
          means the correlation engine turned roughly ten alarm instances into
          one operator-facing incident.
        """

        mtta = await self.session.scalar(
            select(
                func.avg(func.extract("epoch", Incident.acknowledged_at - Incident.created_at))
            ).where(Incident.acknowledged_at.is_not(None))
        )
        mttr = await self.session.scalar(
            select(
                func.avg(func.extract("epoch", Incident.resolved_at - Incident.created_at))
            ).where(Incident.resolved_at.is_not(None))
        )
        incident_total = await self._count()
        link_total = int(
            await self.session.scalar(select(func.count()).select_from(IncidentAlarm)) or 0
        )
        compression = (link_total / incident_total) if incident_total else 0.0
        return {
            "mtta_seconds": float(mtta or 0.0),
            "mttr_seconds": float(mttr or 0.0),
            "alarm_compression": float(compression),
        }


class IncidentWorkflowGate:
    """The one readiness check in front of workflow creation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.context = IncidentContextService(session)
        self.audit = AuditRepository(session)

    async def ensure_ready(self, incident_id: UUID) -> tuple[Incident, Diagnosis]:
        """Return ``(incident, diagnosis)`` when workflow entry is allowed.

        Refusals, in order:

        1. Unknown incident — 404 ``INCIDENT_NOT_FOUND``.
        2. Status cannot legally move to ``UNDER_ANALYSIS`` — 409
           ``INCIDENT_NOT_READY`` with ``reason="INCIDENT_STATUS"``.
        3. No diagnosis is associated, or the newest one has no device, or it
           is not ``FAULT``/``UNCERTAIN`` — 409 ``INCIDENT_NOT_READY`` with
           ``reason="DIAGNOSIS"``.

        Everything past this point is the existing engine's own validation.
        """

        incident = await self.context.get_incident(incident_id)
        try:
            current = IncidentStatus(incident.status)
        except ValueError as exc:
            raise IncidentNotReadyError(
                f"incident status {incident.status!r} is not part of the lifecycle vocabulary",
                {"incident_id": str(incident.id), "reason": "INCIDENT_STATUS"},
            ) from exc
        if current not in WORKFLOW_ENTRY_STATUSES:
            raise IncidentNotReadyError(
                f"incident is {current.value}; the decision workflow starts from "
                f"{sorted(status.value for status in WORKFLOW_ENTRY_STATUSES)}",
                {
                    "incident_id": str(incident.id),
                    "reason": "INCIDENT_STATUS",
                    "current_status": current.value,
                },
            )
        diagnosis = await self.context.latest_diagnosis(incident.id)
        if (
            diagnosis is None
            or not diagnosis.device_id
            or diagnosis.status not in WORKFLOW_READY_DIAGNOSIS_STATUSES
        ):
            raise IncidentNotReadyError(
                "a FAULT or UNCERTAIN diagnosis identifying a device is required "
                "before the decision workflow can start",
                {"incident_id": str(incident.id), "reason": "DIAGNOSIS"},
            )
        return incident, diagnosis

    def record_gate_pass(self, incident: Incident, diagnosis: Diagnosis) -> None:
        """Write one audit row recording that the gate let a workflow start."""

        self.audit.add(
            trace_id=trace_id_context.get(),
            actor="incident-center",
            action="INCIDENT_WORKFLOW_REQUESTED",
            resource=str(incident.id),
            status="SUCCESS",
            details={"diagnosis_id": str(diagnosis.id)},
        )


__all__ = [
    "CRITICAL_SEVERITY",
    "WORKFLOW_ENTRY_STATUSES",
    "WORKFLOW_READY_DIAGNOSIS_STATUSES",
    "IncidentNotReadyError",
    "IncidentOperationsService",
    "IncidentWorkflowGate",
]
