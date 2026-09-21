"""LangGraph orchestration; business persistence remains in WorkflowService."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar

import httpx
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy, interrupt

from app.workflow.contracts import (
    AgentInvocation,
    ApprovalSnapshot,
    MaintenancePlanOutput,
    PolicyDecision,
    PolicyDecisionType,
    SafetyReview,
    TriageResult,
    WorkflowState,
    WorkflowStatus,
)
from app.workflow.policy import POLICY_VERSION, decide
from app.workflow.provider import PROMPT_VERSIONS, AgentModelProvider

AgentAudit = Callable[
    [
        str,
        str,
        str,
        dict[str, Any],
        int | None,
        int | None,
        int,
        int,
        float,
        str | None,
    ],
    Awaitable[None],
]
AgentOutputT = TypeVar("AgentOutputT", TriageResult, MaintenancePlanOutput, SafetyReview)


def _state(value: WorkflowState | dict[str, Any]) -> WorkflowState:
    return value if isinstance(value, WorkflowState) else WorkflowState.model_validate(value)


def _invocation(state: WorkflowState) -> AgentInvocation:
    return AgentInvocation(
        diagnosis=state.diagnosis,
        sensor_evidence=state.sensor_evidence,
        knowledge_context=state.knowledge_context,
        triage_result=state.triage_result,
        maintenance_plan=state.maintenance_plan,
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _is_transient_provider_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500


def build_graph(
    *,
    provider: AgentModelProvider,
    checkpointer: BaseCheckpointSaver[Any],
    audit: AgentAudit,
    max_attempts: int,
    backoff_seconds: float,
    node_timeout_seconds: float,
) -> Any:
    transient_retry = RetryPolicy(
        initial_interval=backoff_seconds,
        backoff_factor=2.0,
        max_interval=max(backoff_seconds, 8.0),
        max_attempts=max_attempts,
        jitter=False,
        retry_on=_is_transient_provider_error,
    )

    async def invoke_agent(
        agent: str,
        state: WorkflowState,
        output_schema: type[AgentOutputT],
    ) -> AgentOutputT:
        started = time.perf_counter()
        try:
            output, usage = await provider.generate(agent, _invocation(state), output_schema)
        except Exception as exc:
            request_count = int(getattr(exc, "request_count", 1))
            schema_retries = int(getattr(exc, "schema_retries", 0))
            input_tokens = getattr(exc, "input_tokens", None)
            output_tokens = getattr(exc, "output_tokens", None)
            await audit(
                agent,
                PROMPT_VERSIONS[agent],
                str(state.diagnosis_id),
                {},
                input_tokens,
                output_tokens,
                request_count,
                schema_retries,
                (time.perf_counter() - started) * 1000.0,
                f"{type(exc).__name__}: {exc}",
            )
            raise
        await audit(
            agent,
            PROMPT_VERSIONS[agent],
            str(state.diagnosis_id),
            output.model_dump(mode="json"),
            usage.input_tokens,
            usage.output_tokens,
            usage.request_count,
            usage.schema_retries,
            (time.perf_counter() - started) * 1000.0,
            None,
        )
        return output

    async def triage_node(raw: WorkflowState) -> dict[str, Any]:
        state = _state(raw)
        output = await invoke_agent("triage", state, TriageResult)
        return {
            "triage_result": output.model_dump(mode="json"),
            "status": WorkflowStatus.TRIAGED.value,
            "current_stage": WorkflowStatus.TRIAGED.value,
            "attempt_count": state.attempt_count + 1,
            "updated_at": _now().isoformat(),
        }

    def precondition_gate(raw: WorkflowState) -> dict[str, Any]:
        state = _state(raw)
        return {"updated_at": state.updated_at.isoformat()}

    def route_precondition(raw: WorkflowState) -> Literal["precondition_block", "triage"]:
        state = _state(raw)
        if state.knowledge_context.sufficiency == "INSUFFICIENT_EVIDENCE":
            return "precondition_block"
        if state.diagnosis.status != "FAULT":
            return "precondition_block"
        return "triage"

    def precondition_block(raw: WorkflowState) -> dict[str, Any]:
        state = _state(raw)
        reasons = []
        if state.knowledge_context.sufficiency == "INSUFFICIENT_EVIDENCE":
            reasons.append("INSUFFICIENT_EVIDENCE")
        if state.diagnosis.status != "FAULT":
            reasons.append("NEEDS_MORE_DIAGNOSTIC_EVIDENCE")
        return {
            "policy_decision": PolicyDecision(
                decision=PolicyDecisionType.BLOCKED,
                policy_version=POLICY_VERSION,
                reasons=reasons,
            ).model_dump(mode="json"),
            "status": WorkflowStatus.BLOCKED.value,
            "current_stage": WorkflowStatus.BLOCKED.value,
            "updated_at": _now().isoformat(),
        }

    async def planning_node(raw: WorkflowState) -> dict[str, Any]:
        state = _state(raw)
        output = await invoke_agent("planning", state, MaintenancePlanOutput)
        return {
            "maintenance_plan": output.model_dump(mode="json"),
            "status": WorkflowStatus.PLAN_READY.value,
            "current_stage": WorkflowStatus.PLAN_READY.value,
            "attempt_count": state.attempt_count + 1,
            "updated_at": _now().isoformat(),
        }

    async def safety_node(raw: WorkflowState) -> dict[str, Any]:
        state = _state(raw)
        output = await invoke_agent("safety_review", state, SafetyReview)
        return {
            "safety_review": output.model_dump(mode="json"),
            "status": WorkflowStatus.SAFETY_REVIEW.value,
            "current_stage": WorkflowStatus.SAFETY_REVIEW.value,
            "attempt_count": state.attempt_count + 1,
            "updated_at": _now().isoformat(),
        }

    def policy_node(raw: WorkflowState) -> dict[str, Any]:
        state = _state(raw)
        assert state.triage_result and state.maintenance_plan and state.safety_review
        decision = decide(
            plan=state.maintenance_plan,
            review=state.safety_review,
            valid_evidence_ids={item.evidence_id for item in state.knowledge_context.evidence},
            diagnosis_status=state.diagnosis.status,
            diagnosed_severity=state.diagnosis.severity,
            knowledge_sufficiency=state.knowledge_context.sufficiency,
        )
        status = WorkflowStatus(decision.decision)
        return {
            "policy_decision": decision.model_dump(mode="json"),
            "status": status.value,
            "current_stage": status.value,
            "updated_at": _now().isoformat(),
        }

    def route_policy(
        raw: WorkflowState,
    ) -> Literal["blocked", "approval", "auto_allowed"]:
        state = _state(raw)
        assert state.policy_decision
        if state.policy_decision.decision == PolicyDecisionType.BLOCKED:
            return "blocked"
        if state.policy_decision.decision == PolicyDecisionType.REQUIRES_APPROVAL:
            return "approval"
        return "auto_allowed"

    def blocked_node(raw: WorkflowState) -> dict[str, Any]:
        return {
            "status": WorkflowStatus.BLOCKED.value,
            "current_stage": WorkflowStatus.BLOCKED.value,
            "updated_at": _now().isoformat(),
        }

    def auto_allowed_node(raw: WorkflowState) -> dict[str, Any]:
        return {
            "status": WorkflowStatus.AUTO_ALLOWED.value,
            "current_stage": WorkflowStatus.AUTO_ALLOWED.value,
            "updated_at": _now().isoformat(),
        }

    def approval_node(
        raw: WorkflowState,
    ) -> Command[Literal["approved", "rejected"]]:
        state = _state(raw)
        decision = interrupt(
            {
                "workflow_run_id": str(state.workflow_run_id),
                "plan_version": state.plan_version,
                "policy_reasons": state.policy_decision.reasons if state.policy_decision else [],
                "message": "Human approval is required before creating a work-order draft.",
            }
        )
        approval = ApprovalSnapshot.model_validate(decision)
        return Command(
            update={
                "approval": approval.model_dump(mode="json"),
                "updated_at": _now().isoformat(),
            },
            goto="approved" if approval.status == "APPROVED" else "rejected",
        )

    def approved_node(raw: WorkflowState) -> dict[str, Any]:
        return {
            "status": WorkflowStatus.APPROVED.value,
            "current_stage": WorkflowStatus.APPROVED.value,
            "updated_at": _now().isoformat(),
        }

    def rejected_node(raw: WorkflowState) -> dict[str, Any]:
        return {
            "status": WorkflowStatus.REJECTED.value,
            "current_stage": WorkflowStatus.REJECTED.value,
            "updated_at": _now().isoformat(),
        }

    # LangGraph's callable protocols currently reject valid Pydantic-state node
    # signatures under mypy even though they are supported at runtime.
    builder: Any = StateGraph(WorkflowState)
    builder.add_node("precondition_gate", precondition_gate)
    builder.add_node(
        "triage", triage_node, retry_policy=transient_retry, timeout=node_timeout_seconds
    )
    builder.add_node("precondition_block", precondition_block)
    builder.add_node(
        "planning", planning_node, retry_policy=transient_retry, timeout=node_timeout_seconds
    )
    builder.add_node(
        "safety", safety_node, retry_policy=transient_retry, timeout=node_timeout_seconds
    )
    builder.add_node("policy", policy_node)
    builder.add_node("blocked", blocked_node)
    builder.add_node("approval", approval_node, destinations=("approved", "rejected"))
    builder.add_node("auto_allowed", auto_allowed_node)
    builder.add_node("approved", approved_node)
    builder.add_node("rejected", rejected_node)
    builder.add_edge(START, "precondition_gate")
    builder.add_conditional_edges("precondition_gate", route_precondition)
    builder.add_edge("precondition_block", END)
    builder.add_edge("triage", "planning")
    builder.add_edge("planning", "safety")
    builder.add_edge("safety", "policy")
    builder.add_conditional_edges("policy", route_policy)
    builder.add_edge("blocked", END)
    builder.add_edge("auto_allowed", END)
    builder.add_edge("approved", END)
    builder.add_edge("rejected", END)
    return builder.compile(checkpointer=checkpointer)
