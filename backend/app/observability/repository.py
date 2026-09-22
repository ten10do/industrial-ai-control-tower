"""Database access for the Agent Observability layer.

This module owns the three observability tables and nothing else. It does not
read or write workflow, approval, or work-order state beyond the foreign key
that links a trace to its authoritative ``workflow_runs`` row.

Counts, token totals, and averages are computed with exact SQL aggregates.
Percentiles need the full sample set, so a bounded recent window is loaded for
that purpose (``MAX_RUN_SAMPLES``); ordering is stable, so the window is
reproducible.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.metrics import (
    AgentAggregate,
    RawObservabilityStats,
    RunCounters,
    RunLatency,
    StepLatency,
    TokenTotals,
)
from app.observability.models import (
    TERMINAL_STATUSES,
    AgentStepDraft,
    ObservabilityMetric,
    ObservabilityRun,
    ObservabilityStep,
    utc_now,
)

MAX_RUN_SAMPLES = 1_000
MAX_STEP_SAMPLES = 5_000

_STATUSES = {
    "RUNNING": "RUNNING",
    "WAITING_APPROVAL": "WAITING_APPROVAL",
    "SUCCESS": "SUCCESS",
    "FAILED": "FAILED",
    "BLOCKED": "BLOCKED",
    "CANCELLED": "CANCELLED",
}


class ObservabilityRepository:
    """Persistence gateway for traced Agent workflow runs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _count(self, statement: Select[Any]) -> int:
        value = await self.session.scalar(statement)
        return int(value or 0)

    async def _optional_int(self, statement: Select[Any]) -> int | None:
        value = await self.session.scalar(statement)
        return None if value is None else int(value)

    async def _optional_float(self, statement: Select[Any]) -> float | None:
        value = await self.session.scalar(statement)
        return None if value is None else float(value)

    async def _count_status(self, status: str) -> int:
        return await self._count(
            select(func.count())
            .select_from(ObservabilityRun)
            .where(ObservabilityRun.status == status)
        )

    async def create_run(
        self,
        *,
        workflow_name: str,
        workflow_run_id: UUID | None,
        device_id: str | None,
        trace_id: str | None,
        provider: str | None,
        model: str | None,
        start_time: datetime | None = None,
    ) -> ObservabilityRun:
        row = ObservabilityRun(
            workflow_run_id=workflow_run_id,
            workflow_name=workflow_name,
            device_id=device_id,
            trace_id=trace_id,
            provider=provider,
            model=model,
            status=_STATUSES["RUNNING"],
            start_time=start_time or utc_now(),
            result={},
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_run(self, run_id: UUID) -> ObservabilityRun | None:
        return await self.session.get(ObservabilityRun, run_id)

    async def find_run_by_workflow_run(self, workflow_run_id: UUID) -> ObservabilityRun | None:
        row: ObservabilityRun | None = await self.session.scalar(
            select(ObservabilityRun)
            .where(ObservabilityRun.workflow_run_id == workflow_run_id)
            .order_by(ObservabilityRun.start_time.desc())
            .limit(1)
        )
        return row

    async def list_runs(
        self,
        *,
        limit: int = 50,
        status: str | None = None,
        workflow_name: str | None = None,
    ) -> list[ObservabilityRun]:
        statement = select(ObservabilityRun)
        if status:
            statement = statement.where(ObservabilityRun.status == status)
        if workflow_name:
            statement = statement.where(ObservabilityRun.workflow_name == workflow_name)
        statement = statement.order_by(ObservabilityRun.start_time.desc()).limit(limit)
        return list(await self.session.scalars(statement))

    async def finalize_run(
        self,
        run: ObservabilityRun,
        *,
        status: str,
        end_time: datetime | None,
        latency_ms: float | None,
        result: dict[str, Any],
        error_message: str | None,
    ) -> ObservabilityRun:
        run.status = status
        run.end_time = end_time
        run.latency_ms = latency_ms
        run.result = result
        run.error_message = error_message
        await self.session.flush()
        return run

    async def replace_steps(
        self, run_id: UUID, drafts: Sequence[AgentStepDraft]
    ) -> list[ObservabilityStep]:
        """Replace the materialised step projection for one run.

        Materialisation is a re-derivable projection of the Phase 5 audit trail,
        so it is rewritten rather than appended to. Only the two observability
        step tables are affected; ``agent_runs`` is never modified.
        """
        await self.session.execute(
            delete(ObservabilityMetric).where(ObservabilityMetric.run_id == run_id)
        )
        await self.session.execute(
            delete(ObservabilityStep).where(ObservabilityStep.run_id == run_id)
        )
        await self.session.flush()
        rows: list[ObservabilityStep] = []
        for draft in drafts:
            step = ObservabilityStep(
                run_id=run_id,
                source_agent_run_id=draft.source_agent_run_id,
                sequence=draft.sequence,
                agent_name=draft.agent_name,
                provider=draft.provider,
                model=draft.model,
                prompt_version=draft.prompt_version,
                status=draft.status,
                start_time=draft.start_time,
                end_time=draft.end_time,
                latency_ms=draft.latency_ms,
                input_summary=draft.input_summary,
                output_summary=draft.output_summary,
                error=draft.error,
            )
            self.session.add(step)
            await self.session.flush()
            self.session.add(
                ObservabilityMetric(
                    step_id=step.step_id,
                    run_id=run_id,
                    agent_name=draft.agent_name,
                    input_tokens=draft.input_tokens,
                    output_tokens=draft.output_tokens,
                    total_tokens=draft.total_tokens,
                    latency_ms=draft.latency_ms,
                    request_count=draft.request_count,
                    schema_retries=draft.schema_retries,
                )
            )
            rows.append(step)
        await self.session.flush()
        return rows

    async def list_steps(
        self, run_id: UUID
    ) -> list[tuple[ObservabilityStep, ObservabilityMetric | None]]:
        steps = list(
            await self.session.scalars(
                select(ObservabilityStep)
                .where(ObservabilityStep.run_id == run_id)
                .order_by(ObservabilityStep.sequence)
            )
        )
        if not steps:
            return []
        metrics = {
            row.step_id: row
            for row in await self.session.scalars(
                select(ObservabilityMetric).where(ObservabilityMetric.run_id == run_id)
            )
        }
        return [(step, metrics.get(step.step_id)) for step in steps]

    async def step_counts(self, run_ids: Sequence[UUID]) -> dict[UUID, int]:
        if not run_ids:
            return {}
        rows = await self.session.execute(
            select(ObservabilityStep.run_id, func.count())
            .where(ObservabilityStep.run_id.in_(list(run_ids)))
            .group_by(ObservabilityStep.run_id)
        )
        return {run_id: int(count) for run_id, count in rows.all()}

    async def token_totals_by_run(self, run_ids: Sequence[UUID]) -> dict[UUID, int | None]:
        if not run_ids:
            return {}
        rows = await self.session.execute(
            select(ObservabilityMetric.run_id, func.sum(ObservabilityMetric.total_tokens))
            .where(ObservabilityMetric.run_id.in_(list(run_ids)))
            .group_by(ObservabilityMetric.run_id)
        )
        return {run_id: None if total is None else int(total) for run_id, total in rows.all()}

    async def collect_stats(self, *, today_start: datetime) -> RawObservabilityStats:
        """Collect every aggregate needed by the metrics contract."""
        terminal = [status.value for status in TERMINAL_STATUSES]
        counters = RunCounters(
            total_runs=await self._count(select(func.count()).select_from(ObservabilityRun)),
            runs_running=await self._count_status("RUNNING"),
            runs_waiting_approval=await self._count_status("WAITING_APPROVAL"),
            runs_today=await self._count(
                select(func.count())
                .select_from(ObservabilityRun)
                .where(ObservabilityRun.start_time >= today_start)
            ),
            success_count=await self._count_status("SUCCESS"),
            failure_count=await self._count_status("FAILED"),
            blocked_count=await self._count_status("BLOCKED"),
            cancelled_count=await self._count_status("CANCELLED"),
        )
        run_latency = RunLatency(
            avg_ms=await self._optional_float(
                select(func.avg(ObservabilityRun.latency_ms)).where(
                    ObservabilityRun.status.in_(terminal),
                    ObservabilityRun.latency_ms.is_not(None),
                )
            ),
            samples_ms=[
                float(value)
                for value in await self.session.scalars(
                    select(ObservabilityRun.latency_ms)
                    .where(
                        ObservabilityRun.status.in_(terminal),
                        ObservabilityRun.latency_ms.is_not(None),
                    )
                    .order_by(ObservabilityRun.start_time.desc())
                    .limit(MAX_RUN_SAMPLES)
                )
                if value is not None
            ],
        )
        step_latency = StepLatency(
            avg_ms=await self._optional_float(
                select(func.avg(ObservabilityStep.latency_ms)).where(
                    ObservabilityStep.latency_ms.is_not(None)
                )
            )
        )
        tokens = TokenTotals(
            input_tokens=await self._optional_int(
                select(func.sum(ObservabilityMetric.input_tokens))
            ),
            output_tokens=await self._optional_int(
                select(func.sum(ObservabilityMetric.output_tokens))
            ),
            total_tokens=await self._optional_int(
                select(func.sum(ObservabilityMetric.total_tokens))
            ),
            steps_with_token_data=await self._count(
                select(func.count())
                .select_from(ObservabilityMetric)
                .where(ObservabilityMetric.total_tokens.is_not(None))
            ),
            steps_total=await self._count(select(func.count()).select_from(ObservabilityStep)),
        )
        status_rows = await self.session.execute(
            select(ObservabilityStep.status, func.count()).group_by(ObservabilityStep.status)
        )
        step_status_counts = {str(status): int(count) for status, count in status_rows.all()}
        sample_rows = await self.session.execute(
            select(ObservabilityStep.agent_name, ObservabilityStep.latency_ms)
            .where(ObservabilityStep.latency_ms.is_not(None))
            .order_by(ObservabilityStep.end_time.desc())
            .limit(MAX_STEP_SAMPLES)
        )
        latency_samples: dict[str, list[float]] = {}
        for agent_name, latency_ms in sample_rows.all():
            if latency_ms is not None:
                latency_samples.setdefault(str(agent_name), []).append(float(latency_ms))
        agent_rows = await self.session.execute(
            select(
                ObservabilityMetric.agent_name,
                func.count(),
                func.sum(case((ObservabilityStep.status == "FAILED", 1), else_=0)),
                func.sum(ObservabilityStep.latency_ms),
                func.count(ObservabilityStep.latency_ms),
                func.sum(ObservabilityMetric.total_tokens),
                func.sum(ObservabilityMetric.schema_retries),
            )
            .join(ObservabilityStep, ObservabilityStep.step_id == ObservabilityMetric.step_id)
            .group_by(ObservabilityMetric.agent_name)
            .order_by(ObservabilityMetric.agent_name)
        )
        by_agent = [
            AgentAggregate(
                agent_name=str(agent_name),
                steps_total=int(steps_total or 0),
                failures=int(failures or 0),
                latency_sum_ms=float(latency_sum or 0.0),
                latency_count=int(latency_count or 0),
                latency_samples_ms=latency_samples.get(str(agent_name), []),
                total_tokens=None if total_tokens is None else int(total_tokens),
                schema_retries=None if retries is None else int(retries),
            )
            for (
                agent_name,
                steps_total,
                failures,
                latency_sum,
                latency_count,
                total_tokens,
                retries,
            ) in agent_rows.all()
        ]
        return RawObservabilityStats(
            counters=counters,
            run_latency=run_latency,
            step_latency=step_latency,
            tokens=tokens,
            step_status_counts=step_status_counts,
            by_agent=by_agent,
        )
