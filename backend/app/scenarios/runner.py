"""Run declarative scenarios through the existing production service path."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from redis.asyncio import Redis
from simulator.engine import SimulationClock, SimulationEngine  # type: ignore[import-not-found]
from simulator.faults import FaultConfig, FaultManager  # type: ignore[import-not-found]
from simulator.models import IndustrialMotor, Telemetry  # type: ignore[import-not-found]
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.errors import AppError
from app.incidents.rules import canonical_readings, evaluate_rules
from app.knowledge.contracts import KnowledgeQuery, KnowledgeSearchResponse
from app.knowledge.query import build_query
from app.knowledge.retrieval import DEFAULT_PIPELINE, KnowledgeIndex
from app.models import Alarm, Approval, Diagnosis, Incident, WorkflowRun, WorkOrder
from app.repositories.alarm_rule import AlarmRuleRepository
from app.repositories.device import DeviceRepository
from app.repositories.telemetry import TelemetryRepository
from app.scenarios.contracts import FailureType, ScenarioDefinition, ScenarioKind, ScenarioResult
from app.scenarios.evaluator import ObservedScenario, evaluate
from app.scenarios.mqtt_failure import MqttFailureHarness
from app.schemas.device import DeviceCreate
from app.security.policy_engine import GOVERNANCE_UNAVAILABLE, ensure_policy_allows
from app.security.rbac import Principal
from app.services.diagnosis import OnlineDiagnosisCoordinator
from app.services.telemetry import IngestionCounters, TelemetryService
from app.websocket.manager import WebSocketManager
from app.workflow.contracts import (
    DiagnosisSnapshot,
    KnowledgeContextSnapshot,
    KnowledgeEvidence,
    SensorEvidence,
    WorkflowState,
)
from app.workflow.policy import POLICY_VERSION
from app.workflow.provider import PROMPT_VERSIONS
from app.workflow.service import WORKFLOW_VERSION, WorkflowService


class _UnavailableRedis:
    """Dependency fault used to exercise TelemetryService's real fallback path."""

    async def eval(self, *args: Any, **kwargs: Any) -> int:
        raise ConnectionError("Phase 7 injected Redis unavailability")

    async def hget(self, *args: Any, **kwargs: Any) -> bytes | None:
        raise ConnectionError("Phase 7 injected Redis unavailability")


class ScenarioRunner:
    """Evaluation orchestration around production services and persistence."""

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        redis: Redis,
        diagnosis: OnlineDiagnosisCoordinator,
        knowledge_index: KnowledgeIndex | None,
        workflow: WorkflowService | None,
        unavailable_workflow: WorkflowService | None = None,
        mqtt_failure: MqttFailureHarness | None = None,
        websocket_manager: WebSocketManager | None = None,
    ) -> None:
        self.sessions = sessions
        self.redis = redis
        self.diagnosis = diagnosis
        self.knowledge_index = knowledge_index
        self.workflow = workflow
        self.unavailable_workflow = unavailable_workflow
        self.mqtt_failure = mqtt_failure
        self.websocket_manager = websocket_manager or WebSocketManager()
        self.counters = IngestionCounters()

    async def run(self, definition: ScenarioDefinition) -> ScenarioResult:
        started_at = datetime.now(UTC)
        started = time.perf_counter()
        blocked = self._unsupported_failure(definition)
        await self._ensure_device(definition)
        samples = self._samples(definition, started_at)
        mqtt_observation: dict[str, bool] = {}
        if definition.failure == FailureType.MQTT_DISCONNECTED and self.mqtt_failure is not None:
            try:
                mqtt = await self.mqtt_failure.ingest(
                    device_id=definition.device.device_id,
                    samples=samples,
                )
            except Exception as exc:
                reason = f"MQTT failure injection unavailable: {type(exc).__name__}"
                blocked = dict.fromkeys(
                    (
                        "alarm",
                        "incident",
                        "diagnosis",
                        "evidence",
                        "workflow",
                        "safety",
                        "approval",
                        "workorder",
                    ),
                    reason,
                )
                return evaluate(
                    definition,
                    ObservedScenario(blocked=blocked),
                    started_at=started_at,
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                )
            mqtt_observation = {
                "mqtt_disconnected": mqtt.disconnected,
                "mqtt_reconnected": mqtt.reconnected,
                "gateway_degraded": mqtt.gateway_degraded,
                "gateway_recovered": mqtt.gateway_recovered,
            }
        else:
            await self._ingest(definition, samples)
        if definition.kind == ScenarioKind.RECOVERY:
            await self._clear_recovered_alarms(definition.device.device_id)
        observed = await self._observe(definition, blocked, mqtt_observation)
        return evaluate(
            definition,
            observed,
            started_at=started_at,
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _unsupported_failure(self, definition: ScenarioDefinition) -> dict[str, str]:
        if definition.kind != ScenarioKind.FAILURE_INJECTION:
            return {}
        if definition.failure in {
            FailureType.REDIS_UNAVAILABLE,
            FailureType.LLM_PROVIDER_UNAVAILABLE,
            FailureType.GOVERNANCE_UNAVAILABLE,
            FailureType.DUPLICATE_TELEMETRY,
            FailureType.OUT_OF_ORDER_TELEMETRY,
            FailureType.RAG_INSUFFICIENT_EVIDENCE,
            FailureType.WORKFLOW_DUPLICATE_REQUEST,
        }:
            if (
                definition.failure == FailureType.LLM_PROVIDER_UNAVAILABLE
                and self.unavailable_workflow is None
            ):
                reason = "real openai_compatible failure provider is unavailable"
                return dict.fromkeys(("workflow", "safety", "approval", "workorder"), reason)
            return {}
        if definition.failure == FailureType.MQTT_DISCONNECTED and self.mqtt_failure is not None:
            return {}
        reason = f"{definition.failure} requires an externally controlled service failure"
        return dict.fromkeys(("workflow", "safety", "approval", "workorder"), reason)

    async def _ensure_device(self, definition: ScenarioDefinition) -> None:
        async with self.sessions() as session:
            repository = DeviceRepository(session)
            if await repository.get(definition.device.device_id) is None:
                await repository.create(
                    DeviceCreate(
                        device_id=definition.device.device_id,
                        device_type=definition.device.device_type,
                        name=definition.device.device_id,
                        status="ACTIVE",
                        metadata={"source": "phase7-scenario"},
                    )
                )
                await session.commit()

    @staticmethod
    def _ticks(seconds: int, interval: float) -> int:
        return max(0, round(seconds / interval))

    def _samples(self, definition: ScenarioDefinition, start: datetime) -> list[Telemetry]:
        interval = definition.execution.sample_interval_seconds
        warmup = self._ticks(definition.execution.warmup_seconds, interval)
        duration = self._ticks(definition.execution.fault_duration_seconds, interval)
        recovery = self._ticks(definition.execution.recovery_seconds, interval)
        motor = IndustrialMotor(
            device_id=definition.device.device_id,
            seed=definition.device.seed,
        )
        manager: FaultManager | None = None
        ramp = 0
        if definition.fault is not None:
            manager = FaultManager(motor.rng)
            ramp = max(1, min(10, duration))
            if definition.kind == ScenarioKind.SINGLE_FAULT:
                ramp = 1
            manager.add_fault(
                FaultConfig(
                    fault_type=definition.fault.type.value,
                    start_tick=warmup,
                    duration=duration,
                    severity=definition.fault.severity,
                    ramp_up_ticks=ramp,
                    recovery_ticks=recovery,
                    target_signal=definition.fault.target_signal,
                )
            )
        total = warmup + ramp + duration + recovery + (1 if definition.fault else 0)
        messages: list[Telemetry] = []
        engine = SimulationEngine(
            motor=motor,
            clock=SimulationClock(start_time=start, tick_duration=interval, realtime=False),
            fault_manager=manager,
            handlers=[messages.append],
        )
        engine.run(max_ticks=max(total, 2))
        if definition.kind == ScenarioKind.DUPLICATE_INPUT or definition.failure == (
            FailureType.DUPLICATE_TELEMETRY
        ):
            messages.insert(len(messages) // 2 + 1, messages[len(messages) // 2])
        if (
            definition.kind == ScenarioKind.OUT_OF_ORDER_INPUT
            or definition.failure == FailureType.OUT_OF_ORDER_TELEMETRY
        ) and len(messages) >= 2:
            messages[-2], messages[-1] = messages[-1], messages[-2]
        return messages

    async def _ingest(self, definition: ScenarioDefinition, samples: list[Telemetry]) -> None:
        topic = f"industrial/devices/{definition.device.device_id}/telemetry"
        redis = self.redis
        if definition.failure == FailureType.REDIS_UNAVAILABLE:
            redis = cast(Redis, _UnavailableRedis())
        async with self.sessions() as session:
            service = TelemetryService(
                session,
                redis,
                self.websocket_manager,
                self.counters,
                self.diagnosis,
            )
            for sample in samples:
                await service.ingest_payload(topic, sample.model_dump_json_mqtt().encode())

    async def _clear_recovered_alarms(self, device_id: str) -> None:
        from app.incidents.service import AlarmLifecycleService

        async with self.sessions() as session:
            device = await DeviceRepository(session).get(device_id)
            latest = await TelemetryRepository(session).latest(device_id)
            if device is None or latest is None:
                return
            rules = await AlarmRuleRepository(session).list_applicable(device.device_type)
            breached_rules = {
                item.rule_id
                for item in evaluate_rules(
                    rules,
                    canonical_readings(
                        {
                            "temperature_c": latest.temperature_c,
                            "bearing_temperature_c": latest.bearing_temperature_c,
                            "vibration_mm_s": latest.vibration_mm_s,
                            "current_a": latest.current_a,
                            "voltage_v": latest.voltage_v,
                            "rpm": latest.rpm,
                            "load_pct": latest.load_pct,
                            "power_kw": latest.power_kw,
                        }
                    ),
                    device_type=device.device_type,
                )
            }
            alarms = list(
                await session.scalars(
                    select(Alarm).where(Alarm.device_id == device_id, Alarm.status != "CLEARED")
                )
            )
            lifecycle = AlarmLifecycleService(session)
            for alarm in alarms:
                if alarm.rule_id in breached_rules:
                    continue
                await lifecycle.clear_alarm(
                    alarm.id,
                    actor="phase7-evaluator",
                    reason="simulator recovery interval completed",
                )

    async def _observe(
        self,
        definition: ScenarioDefinition,
        blocked: dict[str, str],
        injection: dict[str, bool],
    ) -> ObservedScenario:
        device_id = definition.device.device_id
        async with self.sessions() as session:
            alarms = list(await session.scalars(select(Alarm).where(Alarm.device_id == device_id)))
            incidents = list(
                await session.scalars(select(Incident).where(Incident.device_id == device_id))
            )
            diagnosis_query = select(Diagnosis).where(Diagnosis.device_id == device_id)
            if definition.fault is not None:
                diagnosis_query = diagnosis_query.where(
                    Diagnosis.status.in_(["FAULT", "UNCERTAIN"])
                )
            diagnosis = await session.scalar(
                diagnosis_query.order_by(Diagnosis.created_at.desc()).limit(1)
            )

        evidence_sufficiency: str | None = None
        evidence_count = 0
        retrieval: KnowledgeSearchResponse | None = None
        if diagnosis is not None and self.knowledge_index is not None:
            if definition.failure == FailureType.RAG_INSUFFICIENT_EVIDENCE:
                knowledge_query = KnowledgeQuery(
                    device_type="industrial_motor",
                    fault_type="PHASE7_UNSUPPORTED_FAULT",
                    severity=diagnosis.severity,
                    symptoms=["unsupported deterministic acceptance query"],
                )
            else:
                knowledge_query = KnowledgeQuery(
                    device_type="industrial_motor",
                    fault_type=diagnosis.fault_type or "UNSUPPORTED",
                    severity=diagnosis.severity,
                    symptoms=[str(item.get("signal", "")) for item in diagnosis.evidence],
                )
            query = build_query(knowledge_query)
            retrieval = self.knowledge_index.search(query, top_k=5, pipeline=DEFAULT_PIPELINE)
            evidence_sufficiency = str(retrieval.sufficiency.status)
            evidence_count = len(retrieval.evidence)
        elif definition.expected.evidence.required:
            blocked["evidence"] = "RAG index is unavailable"

        workflow_row: WorkflowRun | None = None
        approval: Approval | None = None
        workflow_status: str | None = None
        workflow_provider: str | None = None
        policy_decision: str | None = None
        governance_error: str | None = None
        governance_failed_closed = False
        if definition.failure == FailureType.GOVERNANCE_UNAVAILABLE:
            governance_error, governance_failed_closed = await self._governance_failure()
        if incidents and diagnosis is not None and diagnosis.incident_id is not None:
            if definition.failure == FailureType.GOVERNANCE_UNAVAILABLE or "workflow" in blocked:
                pass
            elif definition.failure == FailureType.RAG_INSUFFICIENT_EVIDENCE:
                if self.workflow is None or retrieval is None:
                    blocked["workflow"] = "real workflow precondition is unavailable"
                    blocked["safety"] = "workflow safety gate was not reached"
                    blocked["approval"] = "workflow approval gate was not reached"
                    blocked["workorder"] = "workflow approval gate was not reached"
                else:
                    (
                        workflow_status,
                        workflow_provider,
                        policy_decision,
                    ) = await self._probe_insufficient_evidence(
                        self.workflow,
                        diagnosis,
                        retrieval,
                        trace_id=f"phase7:{definition.scenario_id}",
                    )
            elif self._workflow_for(definition) is None:
                blocked["workflow"] = "real LLM workflow provider is unavailable"
                blocked["safety"] = "workflow safety gate was not reached"
                blocked["approval"] = "workflow approval gate was not reached"
                blocked["workorder"] = "workflow approval gate was not reached"
            else:
                workflow = self._workflow_for(definition)
                assert workflow is not None
                try:
                    current = await workflow.start(
                        diagnosis.incident_id,
                        diagnosis.id,
                        trace_id=f"phase7:{definition.scenario_id}",
                    )
                    if definition.failure == FailureType.WORKFLOW_DUPLICATE_REQUEST:
                        duplicate = await workflow.start(
                            diagnosis.incident_id,
                            diagnosis.id,
                            trace_id=f"phase7:{definition.scenario_id}:duplicate",
                        )
                        if duplicate.workflow_run_id != current.workflow_run_id:
                            raise AppError(
                                "WORKFLOW_NOT_IDEMPOTENT",
                                "Duplicate workflow start created a second run.",
                                500,
                            )
                    current_approval = await self._pending_approval(current.workflow_run_id)
                    if current_approval is not None and definition.execution.approve:
                        await workflow.decide_approval(
                            current_approval.id,
                            decision="APPROVED",
                            actor="phase7-evaluator",
                            reason="approved by the declared Phase 7 scenario",
                        )
                        if definition.failure == FailureType.WORKFLOW_DUPLICATE_REQUEST:
                            await workflow.decide_approval(
                                current_approval.id,
                                decision="APPROVED",
                                actor="phase7-evaluator",
                                reason="repeated approval delivery for idempotency verification",
                            )
                except AppError:
                    # WorkflowService persists FAILED when an agent call fails.
                    # The observation below records that real production state.
                    pass
            async with self.sessions() as session:
                workflow_row = await session.scalar(
                    select(WorkflowRun)
                    .where(WorkflowRun.incident_id == diagnosis.incident_id)
                    .order_by(WorkflowRun.created_at.desc())
                    .limit(1)
                )
                if workflow_row is not None:
                    approval = await session.scalar(
                        select(Approval).where(Approval.workflow_run_id == workflow_row.id)
                    )
        elif definition.expected.workflow.required:
            blocked["workflow"] = "no incident-linked diagnosis was available"
            blocked["safety"] = "workflow safety gate was not reached"
            blocked["approval"] = "workflow approval gate was not reached"
            blocked["workorder"] = "workflow approval gate was not reached"

        async with self.sessions() as session:
            workorders = list(
                await session.scalars(select(WorkOrder).where(WorkOrder.device_id == device_id))
            )
            execution_authorized = any(
                bool((order.payload or {}).get("execution_authorized")) for order in workorders
            )
            count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(Incident)
                    .where(Incident.device_id == device_id)
                )
                or 0
            )
            workflow_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(WorkflowRun)
                    .where(WorkflowRun.device_id == device_id)
                )
                or 0
            )
        if workflow_row is not None:
            workflow_status = workflow_row.status
            workflow_provider = workflow_row.provider
            policy = (workflow_row.state or {}).get("policy_decision") or {}
            policy_decision = policy.get("decision")
            if policy_decision is None:
                blocked.setdefault("safety", "workflow did not reach the safety policy gate")
        return ObservedScenario(
            alarm_count=len(alarms),
            alarm_occurrences=sum(alarm.occurrence_count for alarm in alarms),
            alarm_severities=sorted({alarm.severity for alarm in alarms}),
            alarm_cleared=bool(alarms) and all(alarm.status == "CLEARED" for alarm in alarms),
            incident_count=count,
            incident_created_at=min((item.created_at for item in incidents), default=None),
            diagnosis_status=diagnosis.status if diagnosis else None,
            diagnosis_fault=diagnosis.fault_type if diagnosis else None,
            diagnosis_created_at=diagnosis.created_at if diagnosis else None,
            evidence_sufficiency=evidence_sufficiency,
            evidence_count=evidence_count,
            workflow_status=workflow_status,
            workflow_provider=workflow_provider,
            workflow_count=workflow_count,
            policy_decision=policy_decision,
            approval_status=approval.decision if approval else None,
            workorder_count=len(workorders),
            execution_authorized=execution_authorized,
            mqtt_disconnected=injection.get("mqtt_disconnected", False),
            mqtt_reconnected=injection.get("mqtt_reconnected", False),
            gateway_degraded=injection.get("gateway_degraded", False),
            gateway_recovered=injection.get("gateway_recovered", False),
            governance_error=governance_error,
            governance_failed_closed=governance_failed_closed,
            blocked=blocked,
        )

    def _workflow_for(self, definition: ScenarioDefinition) -> WorkflowService | None:
        if definition.failure == FailureType.LLM_PROVIDER_UNAVAILABLE:
            return self.unavailable_workflow
        return self.workflow

    async def _pending_approval(self, workflow_id: UUID) -> Approval | None:
        """Return only the pending approval owned by the scenario's workflow."""

        async with self.sessions() as session:
            approval: Approval | None = await session.scalar(
                select(Approval).where(
                    Approval.workflow_run_id == workflow_id,
                    Approval.decision == "PENDING",
                )
            )
            return approval

    @staticmethod
    async def _probe_insufficient_evidence(
        workflow: WorkflowService,
        diagnosis: Diagnosis,
        retrieval: KnowledgeSearchResponse,
        *,
        trace_id: str,
    ) -> tuple[str, str, str | None]:
        """Run the production graph gate with the real unsupported-query retrieval."""

        assert diagnosis.incident_id is not None
        workflow_id = uuid4()
        state = WorkflowState(
            workflow_run_id=workflow_id,
            trace_id=trace_id,
            device_id=diagnosis.device_id or "",
            incident_id=diagnosis.incident_id,
            diagnosis_id=diagnosis.id,
            diagnosis=DiagnosisSnapshot(
                id=diagnosis.id,
                status=diagnosis.status,
                fault_type=diagnosis.fault_type,
                confidence=diagnosis.confidence,
                severity=diagnosis.severity,
                model_version=diagnosis.model_version,
            ),
            sensor_evidence=[SensorEvidence.model_validate(item) for item in diagnosis.evidence],
            knowledge_context=KnowledgeContextSnapshot(
                retrieval_run_id=retrieval.retrieval_run_id,
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
            provider=workflow.provider.provider,
            model=workflow.provider.model,
            prompt_versions=PROMPT_VERSIONS,
            policy_version=POLICY_VERSION,
            workflow_version=WORKFLOW_VERSION,
        )
        graph = workflow._graph(workflow_id, trace_id)
        output = await graph.ainvoke(
            state.model_dump(mode="json"),
            config={"configurable": {"thread_id": str(workflow_id)}},
        )
        final = WorkflowState.model_validate(output)
        decision = str(final.policy_decision.decision) if final.policy_decision else None
        return str(final.status), workflow.provider.provider, decision

    @staticmethod
    async def _governance_failure() -> tuple[str | None, bool]:
        """Exercise the real governance evaluator against unavailable storage."""

        engine = create_async_engine(
            "postgresql+asyncpg://phase7:phase7@127.0.0.1:1/phase7_unreachable",
            connect_args={"timeout": 1.0},
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        principal = Principal(
            user_id=uuid4(),
            username="phase7-governance-probe",
            roles=("ADMIN",),
            permissions=frozenset({"workflow.start"}),
        )
        try:
            async with sessions() as session:
                await ensure_policy_allows(session, principal, "workflow.start")
        except AppError as exc:
            return exc.code, exc.code == GOVERNANCE_UNAVAILABLE and exc.status_code == 503
        finally:
            await engine.dispose()
        return None, False
