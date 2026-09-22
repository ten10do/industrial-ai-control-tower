"""Trace lifecycle for the Agent Observability layer.

Design constraints (Phase 6.6):

* **Non-invasive observation.** The LangGraph graph, agent prompts, safety
  policy, approval flow, work-order logic, and retrieval logic are untouched.
  The tracer observes the ``WorkflowService`` boundary and derives agent steps
  from the audit rows that Phase 5 already writes to ``agent_runs``.
* **No business logic change.** ``ObservableWorkflowService`` delegates every
  call unchanged and re-raises every exception. Tracing failures are logged and
  never propagate into the maintenance decision path.
* **No fabricated metrics.** Token columns stay ``NULL`` when the provider does
  not report usage. Step timestamps are derived from the recorded audit
  timestamp and the measured latency of the real invocation.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AgentRun
from app.observability.models import (
    TERMINAL_STATUSES,
    AgentStepDraft,
    ObservabilityStatus,
    StepStatus,
)
from app.observability.repository import ObservabilityRepository
from app.workflow.contracts import WorkflowRead, WorkflowStatus
from app.workflow.service import WORKFLOW_VERSION, WorkflowService

logger = logging.getLogger(__name__)

WORKFLOW_NAME = WORKFLOW_VERSION
MAX_SUMMARY_CHARS = 400
_AGENT_ORDER = {"triage": 0, "planning": 1, "safety_review": 2}

_SUCCESS_STATUSES = {
    WorkflowStatus.APPROVED,
    WorkflowStatus.AUTO_ALLOWED,
    WorkflowStatus.WORK_ORDER_CREATED,
    WorkflowStatus.REJECTED,
}

_RUNNING_STATUSES = {
    WorkflowStatus.CREATED,
    WorkflowStatus.TRIAGING,
    WorkflowStatus.TRIAGED,
    WorkflowStatus.PLANNING,
    WorkflowStatus.PLAN_READY,
    WorkflowStatus.SAFETY_REVIEW,
}


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def _elapsed_ms(start: datetime, end: datetime) -> float:
    """Return non-negative elapsed milliseconds between two instants."""
    return max(0.0, (end - start).total_seconds() * 1000.0)


def map_workflow_status(status: WorkflowStatus | str) -> ObservabilityStatus:
    """Map an authoritative workflow status onto an observability status.

    ``REJECTED`` maps to ``SUCCESS`` because the workflow executed to completion
    and a human declined the plan; the rejection is preserved in ``result``.
    ``CANCELLED`` is an explicit terminal status rather than being folded into
    ``BLOCKED``, which is reserved for deterministic safety-policy blocks.
    """
    value = WorkflowStatus(status)
    if value in _SUCCESS_STATUSES:
        return ObservabilityStatus.SUCCESS
    if value in {WorkflowStatus.WAITING_APPROVAL, WorkflowStatus.REQUIRES_APPROVAL}:
        return ObservabilityStatus.WAITING_APPROVAL
    if value == WorkflowStatus.BLOCKED:
        return ObservabilityStatus.BLOCKED
    if value == WorkflowStatus.CANCELLED:
        return ObservabilityStatus.CANCELLED
    if value == WorkflowStatus.FAILED:
        return ObservabilityStatus.FAILED
    if value in _RUNNING_STATUSES:
        return ObservabilityStatus.RUNNING
    return ObservabilityStatus.RUNNING


def _truncate(text: str) -> str:
    if len(text) <= MAX_SUMMARY_CHARS:
        return text
    return f"{text[: MAX_SUMMARY_CHARS - 3]}..."


def summarize_input(agent_name: str, input_ref: str | None, payload: dict[str, Any]) -> str:
    """Build a bounded, non-sensitive input summary for one agent step.

    The summary records identifiers and counters only. Prompts, retrieved
    document text, and model reasoning are deliberately excluded.
    """
    parts = [f"agent={agent_name}"]
    if input_ref:
        parts.append(f"diagnosis={input_ref}")
    request_count = payload.get("request_count")
    if request_count is not None:
        parts.append(f"requests={request_count}")
    return _truncate(" ".join(parts))


def summarize_output(agent_name: str, output: dict[str, Any]) -> str | None:
    """Build a bounded summary of a structured agent output.

    Only the validated structured output is summarised; no chain-of-thought or
    raw provider content is stored.
    """
    if not output:
        return None
    if agent_name == "triage":
        return _truncate(f"problem_summary={output.get('problem_summary', '')}")
    if agent_name == "planning":
        steps = output.get("steps") or []
        action_types = [
            str(step.get("action_type", "")) for step in steps if isinstance(step, dict)
        ]
        return _truncate(
            f"objective={output.get('objective', '')} steps={len(steps)} "
            f"action_types={','.join(action_types)}"
        )
    if agent_name == "safety_review":
        hazards = output.get("hazards") or []
        violations = output.get("violations") or []
        return _truncate(f"hazards={len(hazards)} violations={len(violations)}")
    return _truncate(f"keys={','.join(sorted(str(key) for key in output))}")


def _total_tokens(input_tokens: int | None, output_tokens: int | None) -> int | None:
    """Return the token total, or ``None`` when the provider reported nothing."""
    if input_tokens is None and output_tokens is None:
        return None
    return (input_tokens or 0) + (output_tokens or 0)


def build_step_draft(agent_run: AgentRun, sequence: int) -> AgentStepDraft:
    """Derive one step projection from a persisted Phase 5 agent audit row."""
    payload = agent_run.payload or {}
    output = payload.get("output") or {}
    latency_ms = agent_run.latency_ms
    end_time = agent_run.timestamp
    start_time = end_time
    if latency_ms is not None and latency_ms > 0:
        start_time = end_time - timedelta(milliseconds=latency_ms)
    input_tokens = agent_run.input_tokens
    output_tokens = agent_run.output_tokens
    return AgentStepDraft(
        agent_name=agent_run.agent_name,
        sequence=sequence,
        status=(
            StepStatus.SUCCESS.value if agent_run.status == "SUCCESS" else StepStatus.FAILED.value
        ),
        start_time=start_time,
        end_time=end_time,
        latency_ms=latency_ms,
        input_summary=summarize_input(agent_run.agent_name, agent_run.input_ref, payload),
        output_summary=summarize_output(agent_run.agent_name, output),
        error=agent_run.error,
        provider=agent_run.provider,
        model=agent_run.model,
        prompt_version=agent_run.prompt_version,
        source_agent_run_id=agent_run.id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=_total_tokens(input_tokens, output_tokens),
        request_count=payload.get("request_count"),
        schema_retries=payload.get("schema_retries"),
    )


class WorkflowTracer:
    """Record the lifecycle of a workflow execution and its agent steps."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def begin(
        self,
        *,
        device_id: str | None,
        trace_id: str | None,
        provider: str | None,
        model: str | None,
    ) -> UUID | None:
        """Open a run in ``RUNNING`` state. Returns ``None`` if tracing failed."""
        try:
            async with self.sessions() as session:
                run = await ObservabilityRepository(session).create_run(
                    workflow_name=WORKFLOW_NAME,
                    workflow_run_id=None,
                    device_id=device_id,
                    trace_id=trace_id,
                    provider=provider,
                    model=model,
                    start_time=utc_now(),
                )
                run_id = run.run_id
                await session.commit()
                return run_id
        except Exception:
            logger.exception("observability_begin_failed")
            return None

    async def complete(
        self,
        run_id: UUID | None,
        *,
        workflow: WorkflowRead | None,
        result: dict[str, Any],
        error_message: str | None = None,
        status: ObservabilityStatus | None = None,
    ) -> None:
        """Link, materialise, and finalise a traced run. Never raises."""
        if run_id is None:
            return
        try:
            async with self.sessions() as session:
                repository = ObservabilityRepository(session)
                run = await repository.get_run(run_id)
                if run is None:
                    return
                workflow_run_id = workflow.workflow_run_id if workflow else None
                if workflow_run_id is not None:
                    existing = await repository.find_run_by_workflow_run(workflow_run_id)
                    if existing is not None and existing.run_id != run_id:
                        # The workflow service returned an idempotent replay of an
                        # earlier execution, so this provisional run observed no
                        # agent activity. Drop it and refresh the real trace.
                        await session.delete(run)
                        await session.flush()
                        run = existing
                    else:
                        run.workflow_run_id = workflow_run_id
                if workflow is not None:
                    run.device_id = workflow.device_id
                    run.provider = workflow.provider
                    run.model = workflow.model
                resolved = status or (
                    map_workflow_status(workflow.status)
                    if workflow is not None
                    else ObservabilityStatus.FAILED
                )
                drafts = await self._drafts(session, workflow_run_id)
                if drafts:
                    await repository.replace_steps(run.run_id, drafts)
                end_time = utc_now()
                latency_ms = _elapsed_ms(run.start_time, end_time)
                await repository.finalize_run(
                    run,
                    status=resolved.value,
                    end_time=None if resolved not in TERMINAL_STATUSES else end_time,
                    latency_ms=None if resolved not in TERMINAL_STATUSES else latency_ms,
                    result={
                        **(run.result or {}),
                        "workflow_name": WORKFLOW_NAME,
                        "workflow_status": workflow.status.value if workflow else None,
                        "step_count": len(drafts),
                        "outcome": resolved.value,
                        **result,
                    },
                    error_message=error_message,
                )
                await session.commit()
        except Exception:
            logger.exception("observability_complete_failed", extra={"run_id": str(run_id)})

    async def refresh_for_workflow(
        self,
        workflow: WorkflowRead,
        *,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        """Finalise the trace of an already-open run after an approval or cancel."""
        try:
            async with self.sessions() as session:
                repository = ObservabilityRepository(session)
                run = await repository.find_run_by_workflow_run(workflow.workflow_run_id)
                if run is None:
                    return
                status = map_workflow_status(workflow.status)
                drafts = await self._drafts(session, workflow.workflow_run_id)
                if drafts:
                    await repository.replace_steps(run.run_id, drafts)
                end_time = utc_now()
                latency_ms = _elapsed_ms(run.start_time, end_time)
                await repository.finalize_run(
                    run,
                    status=status.value,
                    end_time=None if status not in TERMINAL_STATUSES else end_time,
                    latency_ms=None if status not in TERMINAL_STATUSES else latency_ms,
                    result={
                        **(run.result or {}),
                        "workflow_name": WORKFLOW_NAME,
                        "workflow_status": workflow.status.value,
                        "step_count": len(drafts),
                        "outcome": status.value,
                        **(result or {}),
                    },
                    error_message=error_message,
                )
                await session.commit()
        except Exception:
            logger.exception(
                "observability_refresh_failed",
                extra={"workflow_run_id": str(workflow.workflow_run_id)},
            )

    async def _drafts(
        self, session: AsyncSession, workflow_run_id: UUID | None
    ) -> list[AgentStepDraft]:
        """Materialise agent steps from the Phase 5 audit trail."""
        if workflow_run_id is None:
            return []
        rows = list(
            await session.scalars(
                select(AgentRun)
                .where(AgentRun.workflow_run_id == workflow_run_id)
                .order_by(AgentRun.timestamp)
            )
        )
        ordered = sorted(
            rows,
            key=lambda row: (
                row.timestamp,
                _AGENT_ORDER.get(row.agent_name, len(_AGENT_ORDER)),
            ),
        )
        return [build_step_draft(row, index) for index, row in enumerate(ordered)]


class ObservableWorkflowService(WorkflowService):
    """Observe a ``WorkflowService`` without changing its behaviour.

    The class extends the wrapped service and overrides only the three methods
    that open, resume, or close an execution lifecycle. Every other behaviour is
    inherited unchanged, and overridden methods call ``super()`` and pass the
    result through untouched. The safety policy, approval flow, work-order
    semantics, and agent graph remain exactly as implemented in Phase 5.
    """

    def __init__(self, service: WorkflowService, tracer: WorkflowTracer) -> None:
        super().__init__(
            sessions=service.sessions,
            knowledge_index=service.knowledge_index,
            provider=service.provider,
            checkpointer=service.checkpointer,
            max_attempts=service.max_attempts,
            backoff_seconds=service.backoff_seconds,
            timeout_seconds=service.timeout_seconds,
        )
        self._tracer = tracer

    async def start(self, incident_id: UUID, diagnosis_id: UUID, trace_id: str) -> WorkflowRead:
        run_id = await self._tracer.begin(
            device_id=None,
            trace_id=trace_id,
            provider=getattr(self.provider, "provider", None),
            model=getattr(self.provider, "model", None),
        )
        started = time.perf_counter()
        try:
            workflow = await super().start(incident_id, diagnosis_id, trace_id)
        except Exception as exc:
            await self._tracer.complete(
                run_id,
                workflow=None,
                result={
                    "incident_id": str(incident_id),
                    "diagnosis_id": str(diagnosis_id),
                    "attempt_seconds": round(time.perf_counter() - started, 3),
                },
                error_message=f"{type(exc).__name__}: {exc}",
                status=ObservabilityStatus.FAILED,
            )
            raise
        await self._tracer.complete(
            run_id,
            workflow=workflow,
            result={
                "incident_id": str(incident_id),
                "diagnosis_id": str(diagnosis_id),
                "work_order_created": workflow.state.work_order_id is not None,
            },
        )
        return workflow

    async def decide_approval(
        self, approval_id: UUID, *, decision: str, actor: str, reason: str
    ) -> WorkflowRead:
        workflow = await super().decide_approval(
            approval_id, decision=decision, actor=actor, reason=reason
        )
        await self._tracer.refresh_for_workflow(
            workflow,
            result={
                "approval_id": str(approval_id),
                "decision": decision,
                "actor": actor,
                "reason": reason,
                "work_order_created": workflow.state.work_order_id is not None,
            },
        )
        return workflow

    async def cancel(self, workflow_id: UUID) -> WorkflowRead:
        workflow = await super().cancel(workflow_id)
        await self._tracer.refresh_for_workflow(workflow, result={"cancelled": True})
        return workflow
