"""Phase 6.10 platform endpoints: Prometheus exposition and platform metrics.

``GET /metrics`` is Prometheus exposition format, unauthenticated and
unprefixed, as the scrape convention expects. The active-count gauges are set
from the database at scrape time; if the database is unreachable the gauges are
left untouched and the exposition still succeeds — a metrics endpoint that
dies with the database would hide every other signal exactly when it matters.

``GET /api/v1/platform/metrics`` is the operator-facing JSON summary:
system uptime, telemetry throughput, and the live incident count.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select

from app.api.dependencies import get_session
from app.incidents.states import open_incident_status_values
from app.models import Alarm, Incident

router = APIRouter(tags=["platform"])

platform_router = APIRouter(prefix="/platform", tags=["platform"])


def _set_active_gauges(session: Any) -> tuple[int, int]:
    """Refresh the scrape-time gauges; return (active alarms, active incidents)."""

    from app.platform_observability.metrics import (
        set_alarm_active_count,
        set_incident_active_count,
    )

    alarm_active = int(
        session.scalar(select(func.count()).select_from(Alarm).where(Alarm.status != "CLEARED"))
        or 0
    )
    incident_active = int(
        session.scalar(
            select(func.count())
            .select_from(Incident)
            .where(Incident.status.in_(open_incident_status_values()))
        )
        or 0
    )
    set_alarm_active_count(alarm_active)
    set_incident_active_count(incident_active)
    return alarm_active, incident_active


@router.get("/metrics")
async def prometheus_metrics(request: Request) -> Response:
    """Prometheus exposition of every platform metric."""

    database = getattr(request.app.state, "database", None)
    if database is not None:
        try:
            async with database.sessions() as session:
                _set_active_gauges(session)
        except Exception:
            # The exposition must not die with the database. The gauges keep
            # their last-known values; the scrape itself stays valid.
            import logging

            logging.getLogger(__name__).exception("metrics_gauge_refresh_failed")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@platform_router.get("/metrics")
async def platform_metrics(
    request: Request,
    session: Annotated[Any, Depends(get_session)],
) -> dict[str, Any]:
    """Operator summary: uptime, telemetry throughput, live incidents."""

    from app.services.telemetry import IngestionCounters

    started_monotonic = getattr(request.app.state, "process_started_monotonic", None)
    uptime_seconds = (
        max(time.monotonic() - started_monotonic, 0.0) if started_monotonic is not None else 0.0
    )
    counters: IngestionCounters | None = getattr(request.app.state, "ingestion_counters", None)
    persisted = counters.persisted if counters is not None else 0
    telemetry_rate = round(persisted / uptime_seconds, 2) if uptime_seconds > 0 else 0.0
    incident_active = int(
        await session.scalar(
            select(func.count())
            .select_from(Incident)
            .where(Incident.status.in_(open_incident_status_values()))
        )
        or 0
    )
    return {
        "system": {"uptime_seconds": round(uptime_seconds, 1)},
        "pipeline": {"telemetry_rate": telemetry_rate},
        "incident": {"active": incident_active},
    }
