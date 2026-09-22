"""Transactional workflow, approval, plan, audit, and work-order business service."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.knowledge.contracts import KnowledgeQuery
from app.knowledge.query import build_query
from app.knowledge.retrieval import DEFAULT_PIPELINE, PIPELINE_VERSION, KnowledgeIndex
from app.models import (
    AgentRun,
    Approval,
    Diagnosis,
    Incident,
    MaintenancePlan,
    RetrievalRun,
    WorkflowRun,
    WorkOrder,
)
from app.workflow.contracts import (
    ApprovalSnapshot,
    DiagnosisSnapshot,
    KnowledgeContextSnapshot,
    KnowledgeEvidence,
    SensorEvidence,
    WorkflowError,
    WorkflowRead,
    WorkflowState,
    WorkflowStatus,
)
from app.workflow.graph import build_graph
from app.workflow.policy import POLICY_VERSION
from app.workflow.provider import PROMPT_VERSIONS, AgentModelProvider

WORKFLOW_VERSION = "maintenance-decision-workflow-v1"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _hash_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class WorkflowService:
    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        knowledge_index: KnowledgeIndex | None,
        provider: AgentModelProvider,
        checkpointer: BaseCheckpointSaver[Any],
        max_attempts: int,
        backoff_seconds: float,
        timeout_seconds: float,
    ) -> None:
        self.sessions = sessions
        self.knowledge_index = knowledge_index
        self.provider = provider
        self.checkpointer = checkpointer
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.timeout_seconds = timeout_seconds

    def _graph(self, workflow_id: UUID, trace_id: str) -> Any:
        async def audit(
            agent: str,
            prompt_version: str,
            input_ref: str,
            output: dict[str, Any],
            input_tokens: int | None,
            output_tokens: int | None,
            request_count: int,
            schema_retries: int,
            latency_ms: float,
            error: str | None,
        ) -> None:
            async with self.sessions() as session:
                session.add(
                    AgentRun(
                        workflow_run_id=workflow_id,
                        trace_id=trace_id,
                        agent_name=agent,
                        status="FAILURE" if error else "SUCCESS",
                        provider=self.provider.provider,
                        model=self.provider.model,
                        prompt_version=prompt_version,
                        input_ref=input_ref,
                        output_ref=f"workflow:{workflow_id}:{agent}",
                        tool_calls=[],
                        latency_ms=latency_ms,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        error=error,
                        payload={
                            "output": output,
                            "request_count": request_count,
                            "schema_retries": schema_retries,
                        },
                    )
                )
                await session.commit()

        return build_graph(
            provider=self.provider,
            checkpointer=self.checkpointer,
            audit=audit,
            max_attempts=self.max_attempts,
            backoff_seconds=self.backoff_seconds,
            node_timeout_seconds=self.timeout_seconds,
        )

    @staticmethod
    def _read(row: WorkflowRun) -> WorkflowRead:
        return WorkflowRead(
            workflow_run_id=row.id,
            incident_id=row.incident_id,
            diagnosis_id=row.diagnosis_id,
            device_id=row.device_id,
            status=WorkflowStatus(row.status),
            current_stage=row.current_stage,
            workflow_version=row.workflow_version,
            policy_version=row.policy_version,
            provider=row.provider,
            model=row.model,
            state=WorkflowState.model_validate(row.state),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def get(self, workflow_id: UUID) -> WorkflowRead:
        async with self.sessions() as session:
            row = await session.get(WorkflowRun, workflow_id)
            if row is None:
                raise AppError("WORKFLOW_NOT_FOUND", "Workflow was not found.", 404)
            return self._read(row)

    async def trace(self, workflow_id: UUID) -> tuple[WorkflowRead, list[dict[str, Any]]]:
        async with self.sessions() as session:
            row = await session.get(WorkflowRun, workflow_id)
            if row is None:
                raise AppError("WORKFLOW_NOT_FOUND", "Workflow was not found.", 404)
            runs = list(
                await session.scalars(
                    select(AgentRun)
                    .where(AgentRun.workflow_run_id == workflow_id)
                    .order_by(AgentRun.timestamp)
                )
            )
            return self._read(row), [
                {
                    "agent_run_id": str(item.id),
                    "agent": item.agent_name,
                    "provider": item.provider,
                    "model": item.model,
                    "prompt_version": item.prompt_version,
                    "input_ref": item.input_ref,
                    "output_ref": item.output_ref,
                    "structured_output": item.payload.get("output", {}),
                    "tool_calls": item.tool_calls,
                    "request_count": item.payload.get("request_count"),
                    "schema_retries": item.payload.get("schema_retries"),
                    "status": item.status,
                    "latency_ms": item.latency_ms,
                    "input_tokens": item.input_tokens,
                    "output_tokens": item.output_tokens,
                    "error": item.error,
                    "timestamp": item.timestamp.isoformat(),
                }
                for item in runs
            ]

    async def metrics(self) -> dict[str, int | float]:
        async with self.sessions() as session:

            async def count(model: type[Any], *criteria: Any) -> int:
                statement = select(func.count()).select_from(model)
                if criteria:
                    statement = statement.where(*criteria)
                return int(await session.scalar(statement) or 0)

            workflow_latency = await session.scalar(
                select(
                    func.avg(func.extract("epoch", WorkflowRun.updated_at - WorkflowRun.created_at))
                ).where(
                    WorkflowRun.status.in_(
                        [
                            WorkflowStatus.WORK_ORDER_CREATED,
                            WorkflowStatus.BLOCKED,
                            WorkflowStatus.REJECTED,
                            WorkflowStatus.FAILED,
                            WorkflowStatus.CANCELLED,
                        ]
                    )
                )
            )
            agent_latency = await session.scalar(select(func.avg(AgentRun.latency_ms)))
            token_usage = await session.scalar(
                select(
                    func.coalesce(func.sum(AgentRun.input_tokens), 0)
                    + func.coalesce(func.sum(AgentRun.output_tokens), 0)
                )
            )
            return {
                "agent_runs_total": await count(AgentRun),
                "agent_failures_total": await count(AgentRun, AgentRun.status == "FAILURE"),
                "workflow_completed_total": await count(
                    WorkflowRun,
                    WorkflowRun.status == WorkflowStatus.WORK_ORDER_CREATED,
                ),
                "workflow_blocked_total": await count(
                    WorkflowRun, WorkflowRun.status == WorkflowStatus.BLOCKED
                ),
                "human_approval_total": await count(Approval, Approval.decision == "APPROVED"),
                "human_rejection_total": await count(Approval, Approval.decision == "REJECTED"),
                "workflow_latency_seconds_avg": float(workflow_latency or 0.0),
                "agent_latency_ms_avg": float(agent_latency or 0.0),
                "agent_token_usage": int(token_usage or 0),
            }

    async def start(self, incident_id: UUID, diagnosis_id: UUID, trace_id: str) -> WorkflowRead:
        if self.knowledge_index is None:
            raise AppError("INDEX_NOT_AVAILABLE", "Knowledge index is not available.", 503)
        key = _hash_json([str(incident_id), str(diagnosis_id), WORKFLOW_VERSION])
        lock_id = int.from_bytes(bytes.fromhex(key[:16]), signed=True)
        workflow_id = uuid4()
        async with self.sessions() as session:
            await session.execute(select(func.pg_advisory_xact_lock(lock_id)))
            existing = await session.scalar(
                select(WorkflowRun).where(WorkflowRun.idempotency_key == key)
            )
            if existing is not None:
                return self._read(existing)
            incident = await session.get(Incident, incident_id)
            diagnosis = await session.get(Diagnosis, diagnosis_id)
            if incident is None:
                raise AppError("INCIDENT_NOT_FOUND", "Incident was not found.", 404)
            if diagnosis is None or diagnosis.incident_id != incident_id or not diagnosis.device_id:
                raise AppError(
                    "INVALID_WORKFLOW_INPUT",
                    "Diagnosis must exist, belong to the incident, and identify a device.",
                    422,
                )
            if diagnosis.status not in {"FAULT", "UNCERTAIN"}:
                raise AppError(
                    "INVALID_WORKFLOW_INPUT",
                    "Only FAULT or UNCERTAIN diagnoses can start a workflow.",
                    422,
                )
            built = build_query(
                KnowledgeQuery(
                    device_type="industrial_motor",
                    fault_type=diagnosis.fault_type or "UNSUPPORTED",
                    severity=diagnosis.severity,
                    symptoms=[str(item.get("signal", "")) for item in diagnosis.evidence],
                )
            )
            retrieval_id = uuid4()
            retrieval = self.knowledge_index.search(
                built, top_k=5, pipeline=DEFAULT_PIPELINE, run_id=retrieval_id
            )
            dumped_evidence = [item.model_dump(mode="json") for item in retrieval.evidence]
            session.add(
                RetrievalRun(
                    id=retrieval_id,
                    query=built.model_dump(mode="json"),
                    filters=built.filters.model_dump(mode="json"),
                    pipeline_version=PIPELINE_VERSION,
                    corpus_version=retrieval.corpus_version,
                    embedding_version=retrieval.embedding_version,
                    candidate_chunks=dumped_evidence,
                    selected_evidence=dumped_evidence,
                    sufficiency_result=retrieval.sufficiency.model_dump(mode="json"),
                    latency_ms=retrieval.latency_ms,
                )
            )
            state = WorkflowState(
                workflow_run_id=workflow_id,
                trace_id=trace_id,
                device_id=diagnosis.device_id,
                incident_id=incident_id,
                diagnosis_id=diagnosis_id,
                diagnosis=DiagnosisSnapshot.model_validate(
                    {
                        "id": diagnosis.id,
                        "status": diagnosis.status,
                        "fault_type": diagnosis.fault_type,
                        "confidence": diagnosis.confidence,
                        "severity": diagnosis.severity,
                        "model_version": diagnosis.model_version,
                    }
                ),
                sensor_evidence=[
                    SensorEvidence.model_validate(item) for item in diagnosis.evidence
                ],
                knowledge_context=KnowledgeContextSnapshot(
                    retrieval_run_id=retrieval_id,
                    sufficiency=str(retrieval.sufficiency.status),
                    evidence=[
                        KnowledgeEvidence(
                            evidence_id=item.evidence_id,
                            document_id=item.document_id,
                            chunk_id=item.chunk_id,
                            text=item.text,
                            source=item.source,
                            page=item.page,
                            section=item.section,
                        )
                        for item in retrieval.evidence
                    ],
                ),
                provider=self.provider.provider,
                model=self.provider.model,
                prompt_versions=PROMPT_VERSIONS,
                policy_version=POLICY_VERSION,
                workflow_version=WORKFLOW_VERSION,
            )
            row = WorkflowRun(
                id=workflow_id,
                incident_id=incident_id,
                diagnosis_id=diagnosis_id,
                device_id=diagnosis.device_id,
                trace_id=trace_id,
                idempotency_key=key,
                workflow_version=WORKFLOW_VERSION,
                policy_version=POLICY_VERSION,
                provider=self.provider.provider,
                model=self.provider.model,
                prompt_versions=PROMPT_VERSIONS,
                status=state.status,
                current_stage=state.current_stage,
                state=state.model_dump(mode="json"),
                attempt_count=0,
                errors=[],
                plan_version=1,
            )
            session.add(row)
            incident.status = "UNDER_ANALYSIS"
            await session.commit()

        graph = self._graph(workflow_id, trace_id)
        config = {"configurable": {"thread_id": str(workflow_id)}}
        try:
            output = await graph.ainvoke(state.model_dump(mode="json"), config=config)
            final_state = WorkflowState.model_validate(output)
        except Exception as exc:
            await self._mark_failed(workflow_id, "AGENT_FAILURE", str(exc))
            raise AppError("WORKFLOW_FAILED", "Agent workflow failed.", 500) from exc
        interrupted = "__interrupt__" in output
        if interrupted:
            final_state.status = WorkflowStatus.WAITING_APPROVAL
            final_state.current_stage = WorkflowStatus.WAITING_APPROVAL
        return await self._persist_result(final_state, interrupted=interrupted)

    async def _mark_failed(self, workflow_id: UUID, code: str, message: str) -> None:
        async with self.sessions() as session:
            row = await session.get(WorkflowRun, workflow_id)
            if row is None:
                return
            state = WorkflowState.model_validate(row.state)
            state.errors.append(
                WorkflowError(
                    stage=row.current_stage,
                    code=code,
                    message=message,
                    retryable=False,
                )
            )
            state.status = WorkflowStatus.FAILED
            state.current_stage = WorkflowStatus.FAILED
            state.updated_at = _utc_now()
            row.status = state.status
            row.current_stage = state.current_stage
            row.errors = [item.model_dump(mode="json") for item in state.errors]
            row.state = state.model_dump(mode="json")
            await session.commit()

    async def _persist_result(
        self, state: WorkflowState, *, interrupted: bool = False
    ) -> WorkflowRead:
        async with self.sessions() as session:
            row = await session.get(WorkflowRun, state.workflow_run_id, with_for_update=True)
            assert row is not None
            plan: MaintenancePlan | None = None
            if state.maintenance_plan is not None:
                plan = await session.scalar(
                    select(MaintenancePlan).where(
                        MaintenancePlan.workflow_run_id == state.workflow_run_id
                    )
                )
                plan_payload = state.maintenance_plan.model_dump(mode="json")
                plan_hash = _hash_json(plan_payload)
                if plan is None:
                    plan = MaintenancePlan(
                        workflow_run_id=state.workflow_run_id,
                        diagnosis_id=state.diagnosis_id,
                        version=state.plan_version,
                        plan_hash=plan_hash,
                        objective=state.maintenance_plan.objective,
                        steps=[
                            item.model_dump(mode="json") for item in state.maintenance_plan.steps
                        ],
                        tools_required=[],
                        estimated_risk=state.diagnosis.severity,
                        status="READY",
                        payload=plan_payload,
                    )
                    session.add(plan)
                    await session.flush()
            if interrupted and plan is not None:
                assert state.policy_decision is not None
                approval = await session.scalar(
                    select(Approval).where(Approval.workflow_run_id == state.workflow_run_id)
                )
                if approval is None:
                    approval = Approval(
                        workflow_run_id=state.workflow_run_id,
                        maintenance_plan_id=plan.id,
                        decision="PENDING",
                        plan_version=plan.version,
                        plan_hash=plan.plan_hash,
                        payload={"policy_reasons": state.policy_decision.reasons},
                    )
                    session.add(approval)
            if state.status == WorkflowStatus.AUTO_ALLOWED:
                work_order = await self._create_work_order(session, state, plan, None)
                state.work_order_id = work_order.id
                state.status = WorkflowStatus.WORK_ORDER_CREATED
                state.current_stage = WorkflowStatus.WORK_ORDER_CREATED
            row.status = state.status
            row.current_stage = state.current_stage
            row.state = state.model_dump(mode="json")
            row.attempt_count = state.attempt_count
            row.errors = [item.model_dump(mode="json") for item in state.errors]
            incident = await session.get(Incident, state.incident_id)
            if incident is not None:
                if state.status == WorkflowStatus.WAITING_APPROVAL:
                    incident.status = "ACTION_PENDING"
                elif state.status == WorkflowStatus.WORK_ORDER_CREATED:
                    incident.status = "WORK_ORDER_CREATED"
            await session.commit()
            await session.refresh(row)
            return self._read(row)

    async def _create_work_order(
        self,
        session: AsyncSession,
        state: WorkflowState,
        plan: MaintenancePlan | None,
        approval: Approval | None,
    ) -> WorkOrder:
        existing = await session.scalar(
            select(WorkOrder).where(WorkOrder.workflow_run_id == state.workflow_run_id)
        )
        if existing is not None:
            return existing
        if plan is None or state.maintenance_plan is None:
            raise AppError("PLAN_NOT_AVAILABLE", "Maintenance plan is not available.", 409)
        order = WorkOrder(
            workflow_run_id=state.workflow_run_id,
            maintenance_plan_id=plan.id,
            approval_id=approval.id if approval else None,
            device_id=state.device_id,
            incident_id=state.incident_id,
            diagnosis_id=state.diagnosis_id,
            title=f"Inspect {state.diagnosis.fault_type or 'equipment condition'}",
            priority=state.diagnosis.severity or "MEDIUM",
            plan=state.maintenance_plan.model_dump(mode="json"),
            evidence_refs=sorted(
                {
                    evidence_id
                    for step in state.maintenance_plan.steps
                    for evidence_id in step.evidence_ids
                }
            ),
            safety_requirements=state.policy_decision.reasons if state.policy_decision else [],
            status="DRAFT",
            payload={"execution_authorized": False},
        )
        session.add(order)
        await session.flush()
        return order

    async def decide_approval(
        self, approval_id: UUID, *, decision: str, actor: str, reason: str
    ) -> WorkflowRead:
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError(decision)
        async with self.sessions() as session:
            approval = await session.scalar(
                select(Approval).where(Approval.id == approval_id).with_for_update()
            )
            if approval is None or approval.workflow_run_id is None:
                raise AppError("APPROVAL_NOT_FOUND", "Approval was not found.", 404)
            row = await session.get(WorkflowRun, approval.workflow_run_id, with_for_update=True)
            assert row is not None
            if row.status == WorkflowStatus.CANCELLED:
                raise AppError("WORKFLOW_CANCELLED", "Cancelled workflow cannot be approved.", 409)
            plan = await session.get(MaintenancePlan, approval.maintenance_plan_id)
            if (
                plan is None
                or plan.version != approval.plan_version
                or plan.plan_hash != approval.plan_hash
            ):
                raise AppError("STALE_APPROVAL", "Approval does not match the current plan.", 409)
            if approval.decision not in {"PENDING", decision}:
                raise AppError(
                    "APPROVAL_ALREADY_DECIDED", "Approval has the opposite decision.", 409
                )
            if approval.decision == decision and row.status in {
                WorkflowStatus.WORK_ORDER_CREATED,
                WorkflowStatus.REJECTED,
            }:
                return self._read(row)
            approval.decision = decision
            approval.actor = actor
            approval.reason = reason
            approval.decided_at = _utc_now()
            graph = self._graph(row.id, row.trace_id)
            snapshot = ApprovalSnapshot(
                approval_id=approval.id,
                status=decision,
                actor=actor,
                reason=reason,
                plan_version=approval.plan_version,
                plan_hash=approval.plan_hash or "",
                decided_at=approval.decided_at,
            )
            output = await graph.ainvoke(
                Command(resume=snapshot.model_dump(mode="json")),
                config={"configurable": {"thread_id": str(row.id)}},
            )
            state = WorkflowState.model_validate(output)
            state.approval = snapshot
            if decision == "APPROVED":
                work_order = await self._create_work_order(session, state, plan, approval)
                state.work_order_id = work_order.id
                state.status = WorkflowStatus.WORK_ORDER_CREATED
                state.current_stage = WorkflowStatus.WORK_ORDER_CREATED
                incident = await session.get(Incident, state.incident_id)
                if incident is not None:
                    incident.status = "WORK_ORDER_CREATED"
            else:
                state.status = WorkflowStatus.REJECTED
                state.current_stage = WorkflowStatus.REJECTED
            row.status = state.status
            row.current_stage = state.current_stage
            row.state = state.model_dump(mode="json")
            await session.commit()
            await session.refresh(row)
            return self._read(row)

    async def cancel(self, workflow_id: UUID) -> WorkflowRead:
        async with self.sessions() as session:
            row = await session.get(WorkflowRun, workflow_id, with_for_update=True)
            if row is None:
                raise AppError("WORKFLOW_NOT_FOUND", "Workflow was not found.", 404)
            if row.status not in {
                WorkflowStatus.CREATED,
                WorkflowStatus.TRIAGING,
                WorkflowStatus.PLANNING,
                WorkflowStatus.WAITING_APPROVAL,
            }:
                raise AppError("WORKFLOW_NOT_CANCELLABLE", "Workflow cannot be cancelled now.", 409)
            state = WorkflowState.model_validate(row.state)
            state.status = WorkflowStatus.CANCELLED
            state.current_stage = WorkflowStatus.CANCELLED
            state.updated_at = _utc_now()
            row.status = state.status
            row.current_stage = state.current_stage
            row.state = state.model_dump(mode="json")
            await session.commit()
            await session.refresh(row)
            return self._read(row)

    async def pending_approvals(self) -> list[Approval]:
        async with self.sessions() as session:
            return list(
                await session.scalars(
                    select(Approval)
                    .join(WorkflowRun, Approval.workflow_run_id == WorkflowRun.id)
                    .where(Approval.decision == "PENDING")
                    .where(WorkflowRun.status == WorkflowStatus.WAITING_APPROVAL)
                    .order_by(Approval.created_at)
                )
            )

    async def get_approval(self, approval_id: UUID) -> Approval:
        async with self.sessions() as session:
            approval = await session.get(Approval, approval_id)
            if approval is None:
                raise AppError("APPROVAL_NOT_FOUND", "Approval was not found.", 404)
            return approval
