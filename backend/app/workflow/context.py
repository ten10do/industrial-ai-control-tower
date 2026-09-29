"""Bounded, deterministic assembly of the workflow's decision context.

The builder reads the incident's situation once, before any agent runs, and
freezes it into a :class:`~app.workflow.contracts.DecisionContext`. Three
properties are load bearing.

Bounded. Every list is capped by an explicit limit and ordered by a total
ordering whose final key is a stable tiebreaker, so two reads against the same
rows return the same list in the same order regardless of planner choice.

Deterministic. No clock read enters an ordering, no randomness enters a value,
and the current incident is excluded from its own history by primary key. The
same rows always produce the same context.

Honest about baselines. Device health prefers a real device/asset baseline. When
none is configured, it falls back to the simulator constants, and it says so in
``baseline_source``. A fallback is never presented as a measured baseline.

The telemetry and history sections are untrusted input to a language model and
are marked as such when rendered into a prompt. They are assembled here as
plain typed data with no instruction content.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alarm, Approval, Device, Diagnosis, Incident, WorkOrder
from app.workflow.contracts import (
    DecisionContext,
    DeviceHealthSnapshot,
    HistoricalIncidentSummary,
    LinkedAlarmSnapshot,
    PriorWorkOrderSummary,
)

#: Bump whenever a query, a limit, or a derivation changes shape.
CONTEXT_VERSION = "decision-context-v1"

BUILDER_NAME = "DecisionContextBuilder"

#: Hard caps. The historical queries are bounded so a device with a long history
#: never turns one workflow start into an unbounded scan.
HISTORY_LIMIT = 10
ALARM_LIMIT = 20
WORK_ORDER_LIMIT = 10
TELEMETRY_WINDOW = 20

#: Simulator baseline constants. These are the explicit, named fallback used
#: only when the device carries no configured baseline. They mirror
#: ``simulator.simulator.models.IndustrialMotor`` and are duplicated here on
#: purpose: the backend runtime image does not ship the simulator package, and a
#: cross-package import would make the backend depend on a test-only distribution.
SIMULATOR_BASELINE: dict[str, float] = {
    "temperature_c": 25.0,
    "bearing_temperature_c": 25.0,
    "vibration_mm_s": 1.8,
    "current_a": 10.0,
    "voltage_v": 380.0,
    "rpm": 1500.0,
    "load_pct": 50.0,
    "power_kw": 5.5,
}

#: Signals included in the health deviation comparison, each with the ratio at
#: which it is considered to have crossed into a worse band.
_HEALTH_SIGNALS: tuple[str, ...] = (
    "temperature_c",
    "bearing_temperature_c",
    "vibration_mm_s",
    "current_a",
    "power_kw",
)

#: Deviation-ratio band boundaries, evaluated from the highest band down.
_HEALTH_BANDS: tuple[tuple[float, str], ...] = (
    (2.0, "CRITICAL"),
    (1.5, "DEGRADED"),
    (1.15, "ELEVATED"),
    (0.0, "NOMINAL"),
)

#: A telemetry window shorter than two samples cannot support any statistic.
MINIMUM_WINDOW_SAMPLES = 2


class DecisionContextBuilder:
    """Assemble one incident's decision context from bounded, ordered reads."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build(self, incident: Incident, diagnosis: Diagnosis) -> DecisionContext:
        """Return the frozen context for ``incident``.

        ``diagnosis`` is passed in because the workflow already loaded and
        validated it; re-reading it here would risk a second, differently
        ordered row and break reproducibility.
        """

        device_id = incident.device_id or diagnosis.device_id
        if device_id is None:
            device_id = ""

        linked_alarms = await self._linked_alarms(incident.id)
        history = await self._historical_incidents(device_id, incident.id)
        maintenance_history = await self._maintenance_history(device_id)
        prior_diagnosis_id, prior_fault_type = await self._prior_diagnosis(device_id, incident.id)
        device_health = await self._device_health(device_id)

        return DecisionContext(
            incident_id=incident.id,
            device_id=device_id,
            incident_status=incident.status,
            incident_severity=incident.severity,
            incident_priority=incident.priority,
            incident_created_at=incident.created_at,
            linked_alarms=linked_alarms,
            history=history,
            history_limit=HISTORY_LIMIT,
            maintenance_history=maintenance_history,
            device_health=device_health,
            prior_diagnosis_id=prior_diagnosis_id,
            prior_fault_type=prior_fault_type,
            built_by=BUILDER_NAME,
            context_version=CONTEXT_VERSION,
        )

    async def _linked_alarms(self, incident_id: UUID) -> list[LinkedAlarmSnapshot]:
        """Return this incident's alarms, most recent activity first, bounded."""

        from app.incidents.models import IncidentAlarm

        rows = await self.session.scalars(
            select(Alarm)
            .join(IncidentAlarm, IncidentAlarm.alarm_id == Alarm.id)
            .where(IncidentAlarm.incident_id == incident_id)
            .order_by(Alarm.started_at.desc(), Alarm.id.desc())
            .limit(ALARM_LIMIT)
        )
        return [
            LinkedAlarmSnapshot(
                alarm_id=alarm.id,
                rule_id=alarm.rule_id,
                severity=alarm.severity,
                status=alarm.status,
                occurrence_count=alarm.occurrence_count,
                started_at=alarm.started_at,
                last_triggered_at=alarm.last_triggered_at,
            )
            for alarm in rows
        ]

    async def _historical_incidents(
        self, device_id: str, current_incident_id: UUID
    ) -> list[HistoricalIncidentSummary]:
        """Return bounded prior incidents on the same device.

        The current incident is excluded by primary key rather than trusted to
        fall outside a time window: a reopened incident can share its device with
        itself, and a window is not a sufficient exclusion. Ordering ends on
        ``id`` so equal ``created_at`` values never reorder between reads.
        """

        if not device_id:
            return []
        rows = await self.session.scalars(
            select(Incident)
            .where(Incident.device_id == device_id)
            .where(Incident.id != current_incident_id)
            .order_by(Incident.created_at.desc(), Incident.id.desc())
            .limit(HISTORY_LIMIT)
        )
        return [
            HistoricalIncidentSummary(
                incident_id=row.id,
                title=row.title,
                status=row.status,
                severity=row.severity,
                priority=row.priority,
                created_at=row.created_at,
                resolved_at=row.resolved_at,
                closed_at=row.closed_at,
            )
            for row in rows
        ]

    async def _maintenance_history(self, device_id: str) -> list[PriorWorkOrderSummary]:
        """Return bounded prior work orders for the device, newest first."""

        if not device_id:
            return []
        rows = await self.session.execute(
            select(WorkOrder, Approval.decision)
            .outerjoin(Approval, Approval.id == WorkOrder.approval_id)
            .where(WorkOrder.device_id == device_id)
            .order_by(WorkOrder.created_at.desc(), WorkOrder.id.desc())
            .limit(WORK_ORDER_LIMIT)
        )
        return [
            PriorWorkOrderSummary(
                work_order_id=order.id,
                incident_id=order.incident_id,
                status=order.status,
                priority=order.priority,
                approval_status=decision,
                created_at=order.created_at,
            )
            for order, decision in rows
            if order.incident_id is not None
        ]

    async def _prior_diagnosis(
        self, device_id: str, current_incident_id: UUID
    ) -> tuple[UUID | None, str | None]:
        """Return the newest diagnosis on this device from another incident."""

        if not device_id:
            return None, None
        row = await self.session.scalar(
            select(Diagnosis)
            .where(Diagnosis.device_id == device_id)
            .where(Diagnosis.incident_id.is_not(None))
            .where(Diagnosis.incident_id != current_incident_id)
            .order_by(Diagnosis.created_at.desc(), Diagnosis.id.desc())
            .limit(1)
        )
        if row is None:
            return None, None
        return row.id, row.fault_type

    async def _device_health(self, device_id: str) -> DeviceHealthSnapshot | None:
        """Derive health from a fixed telemetry window against a named baseline.

        The window is the most recent ``TELEMETRY_WINDOW`` samples, read in one
        bounded query. No second model call is made: the same deterministic
        statistics the feature pipeline uses are computed here directly, so the
        health summary cannot diverge from the diagnosis path by re-running a
        model with different state.
        """

        if not device_id:
            return None
        from app.repositories.telemetry import TelemetryRepository

        samples = await TelemetryRepository(self.session).recent_window(
            device_id, TELEMETRY_WINDOW
        )
        if len(samples) < MINIMUM_WINDOW_SAMPLES:
            return DeviceHealthSnapshot(
                device_id=device_id,
                window_size=TELEMETRY_WINDOW,
                sample_count=len(samples),
                sufficient=False,
                baseline_source="none",
                band="UNKNOWN",
                notes=["insufficient telemetry samples"],
            )

        baseline, baseline_source = await self._baseline(device_id)
        signals: dict[str, float] = {}
        ratios: dict[str, float] = {}
        for signal in _HEALTH_SIGNALS:
            values = [float(getattr(sample, signal)) for sample in samples]
            mean = sum(values) / len(values)
            signals[signal] = round(mean, 6)
            base = baseline.get(signal)
            if base is None or base == 0:
                continue
            ratios[signal] = round(abs(mean - base) / abs(base), 6)

        max_ratio = max(ratios.values()) if ratios else 0.0
        band = _health_band(max_ratio)
        return DeviceHealthSnapshot(
            device_id=device_id,
            window_size=TELEMETRY_WINDOW,
            window_start=samples[0].timestamp,
            window_end=samples[-1].timestamp,
            sample_count=len(samples),
            sufficient=True,
            baseline_source=baseline_source,
            signals=signals,
            deviation_ratios=ratios,
            max_deviation_ratio=max_ratio,
            band=band,
            notes=[],
        )

    async def _baseline(self, device_id: str) -> tuple[dict[str, float], str]:
        """Resolve the health baseline, preferring real configuration.

        A device/asset baseline is authoritative when present. The simulator
        constants are used only as an explicit, labelled fallback, and never
        silently substituted for a configured value.
        """

        device = await self.session.scalar(select(Device).where(Device.device_id == device_id))
        configured = _configured_baseline(device)
        if configured:
            return configured, "device_config"
        return dict(SIMULATOR_BASELINE), "simulator_fallback"


def _configured_baseline(device: Device | None) -> dict[str, float]:
    """Extract a numeric baseline from a device's configuration metadata.

    The Phase 6.8 device definition carries a typed acquisition configuration
    rather than free numeric baselines, so this reads the conventional
    ``baseline`` bag from device metadata when a deployment supplies one. An
    absent or non-numeric bag returns empty, which routes the caller to the
    explicit simulator fallback.
    """

    if device is None or not device.device_metadata:
        return {}
    candidate = device.device_metadata.get("baseline")
    if not isinstance(candidate, dict):
        return {}
    baseline: dict[str, float] = {}
    for key, value in candidate.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            baseline[str(key)] = float(value)
    return baseline


def _health_band(max_ratio: float) -> str:
    for threshold, band in _HEALTH_BANDS:
        if max_ratio >= threshold:
            return band
    return "NOMINAL"


__all__ = [
    "ALARM_LIMIT",
    "BUILDER_NAME",
    "CONTEXT_VERSION",
    "HISTORY_LIMIT",
    "SIMULATOR_BASELINE",
    "TELEMETRY_WINDOW",
    "WORK_ORDER_LIMIT",
    "DecisionContextBuilder",
]
