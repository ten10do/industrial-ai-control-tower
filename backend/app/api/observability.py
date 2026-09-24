"""Phase 6.6 read-only Agent Observability APIs.

Exposes the persisted trace projection: recent runs, the full trace of one run,
and aggregate execution metrics. No endpoint mutates workflow state.

Phase 6.13-A brings the surface inside the governed perimeter: every read
requires ``observability.read``. The projection may name operators and decision
outcomes, so it is no longer readable without an identity.

The router is declared without a prefix and mounted twice by the application as
``/api/v1/observability`` (the repository-wide API contract namespace) and
``/api/observability`` (the shorthand used by the Phase 6.6 specification).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.core.errors import AppError
from app.observability.metrics import build_metrics
from app.observability.models import (
    AgentMetricRead,
    AgentRunRead,
    AgentRunTrace,
    AgentStepRead,
    ObservabilityMetric,
    ObservabilityMetricsRead,
    ObservabilityRun,
    ObservabilityStatus,
    ObservabilityStep,
)
from app.observability.repository import ObservabilityRepository
from app.security.dependencies import require_permission
from app.security.rbac import OBSERVABILITY_READ, Principal

router = APIRouter(tags=["observability"])

ReadObservability = Annotated[Principal, Depends(require_permission(OBSERVABILITY_READ))]


def _run_read(row: ObservabilityRun, *, step_count: int, total_tokens: int | None) -> AgentRunRead:
    return AgentRunRead(
        run_id=row.run_id,
        workflow_run_id=row.workflow_run_id,
        workflow_name=row.workflow_name,
        device_id=row.device_id,
        trace_id=row.trace_id,
        provider=row.provider,
        model=row.model,
        status=row.status,
        start_time=row.start_time,
        end_time=row.end_time,
        latency_ms=row.latency_ms,
        step_count=step_count,
        total_tokens=total_tokens,
        result=row.result or {},
        error_message=row.error_message,
    )


def _metric_read(
    step: ObservabilityStep, metric: ObservabilityMetric | None
) -> AgentMetricRead | None:
    if metric is None:
        return None
    return AgentMetricRead(
        step_id=step.step_id,
        agent_name=metric.agent_name,
        input_tokens=metric.input_tokens,
        output_tokens=metric.output_tokens,
        total_tokens=metric.total_tokens,
        latency_ms=metric.latency_ms,
        request_count=metric.request_count,
        schema_retries=metric.schema_retries,
        token_data_available=metric.total_tokens is not None,
    )


def _step_read(step: ObservabilityStep, metric: ObservabilityMetric | None) -> AgentStepRead:
    return AgentStepRead(
        step_id=step.step_id,
        agent_name=step.agent_name,
        sequence=step.sequence,
        status=step.status,
        start_time=step.start_time,
        end_time=step.end_time,
        latency_ms=step.latency_ms,
        input_summary=step.input_summary,
        output_summary=step.output_summary,
        error=step.error,
        provider=step.provider,
        model=step.model,
        prompt_version=step.prompt_version,
        metrics=_metric_read(step, metric),
    )


@router.get("/observability/runs", response_model=list[AgentRunRead])
async def list_runs(
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: ReadObservability,
    status: ObservabilityStatus | None = None,
    workflow_name: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AgentRunRead]:
    repository = ObservabilityRepository(session)
    rows = await repository.list_runs(
        limit=limit,
        status=status.value if status else None,
        workflow_name=workflow_name,
    )
    run_ids = [row.run_id for row in rows]
    counts = await repository.step_counts(run_ids)
    tokens = await repository.token_totals_by_run(run_ids)
    return [
        _run_read(
            row,
            step_count=counts.get(row.run_id, 0),
            total_tokens=tokens.get(row.run_id),
        )
        for row in rows
    ]


@router.get("/observability/metrics", response_model=ObservabilityMetricsRead)
async def observability_metrics(
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: ReadObservability,
) -> ObservabilityMetricsRead:
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    repository = ObservabilityRepository(session)
    return build_metrics(await repository.collect_stats(today_start=today_start))


@router.get("/observability/runs/{run_id}", response_model=AgentRunTrace)
async def get_run(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    principal: ReadObservability,
) -> AgentRunTrace:
    repository = ObservabilityRepository(session)
    row = await repository.get_run(run_id)
    if row is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent run trace was not found.", 404)
    pairs = await repository.list_steps(run_id)
    steps = [_step_read(step, metric) for step, metric in pairs]
    token_values = [
        metric.total_tokens
        for _, metric in pairs
        if metric is not None and metric.total_tokens is not None
    ]
    return AgentRunTrace(
        run=_run_read(
            row,
            step_count=len(steps),
            total_tokens=sum(token_values) if token_values else None,
        ),
        steps=steps,
    )
