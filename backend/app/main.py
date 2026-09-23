"""FastAPI application entry point and managed infrastructure lifecycle."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    alarm_rules,
    alarms,
    assets,
    configurations,
    connectivity,
    devices,
    diagnoses,
    knowledge,
    observability,
    telemetry,
    websockets,
    workflows,
)
from app.assetconfig.apply import GatewayDefinitionApplier, UnavailableApplier
from app.assetconfig.errors import AssetConfigError
from app.assetconfig.models import ApplyStatus, ConfigurationSource
from app.assetconfig.repository import ConfigurationRepository
from app.assetconfig.source import resolve_definitions
from app.config import get_settings
from app.core.context import trace_id_context
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.gateway import (
    DeviceRegistrationChecker,
    DeviceRegistry,
    GatewayConfigurationError,
    GatewayIngestionSink,
    IndustrialProtocolGateway,
    RetryPolicy,
)
from app.gateway.simulator_source import build_simulator_source_factory
from app.incidents.errors import AlarmLifecycleError
from app.infrastructure.database.session import Database
from app.infrastructure.mqtt.consumer import MqttTelemetryConsumer
from app.knowledge.retrieval import KnowledgeIndex
from app.ml.runtime import ModelCompatibilityError, ModelRuntime
from app.observability.tracer import ObservableWorkflowService, WorkflowTracer
from app.services.diagnosis import OnlineDiagnosisCoordinator
from app.services.telemetry import IngestionCounters
from app.websocket.manager import WebSocketManager
from app.workflow.provider import AgentModelProvider, OpenAICompatibleProvider, TestProvider
from app.workflow.service import WorkflowService

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


def _error_response(
    code: str,
    message: str,
    trace_id: str,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message, "trace_id": trace_id}
    if details:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"error": error})


async def _build_managed_gateway(
    *,
    sessions: Any,
    policy: RetryPolicy,
    sink: GatewayIngestionSink,
    registration: DeviceRegistrationChecker,
    simulator_source: Any,
    mqtt_connected: Any,
) -> IndustrialProtocolGateway:
    """Build the gateway from published database configurations.

    Published configurations are authoritative. The YAML file only fills devices
    that have no published version, so a restart can never fall back to a stale
    file for a device that has a managed configuration.

    Startup order preserves the Phase 6.7 reliability semantics: every runtime is
    started first, so the bounded retry machinery keeps working, and readiness is
    then recorded per device without tearing any runtime down.
    """

    resolved = await resolve_definitions(
        sessions=sessions,
        yaml_path=settings.gateway_config_path,
        managed=True,
        on_error=lambda message: logger.error(
            "configuration_source_error", extra={"detail": message}
        ),
    )
    registry = DeviceRegistry()
    if resolved:
        registry.load([item.definition for item in resolved])
    gateway = IndustrialProtocolGateway(
        registry=registry,
        sink=sink,
        registration=registration,
        enabled=True,
        config_file=f"configuration-management ({len(resolved)} device(s))",
        policy=policy,
        simulator_source_factory=simulator_source,
        mqtt_connected=mqtt_connected,
    )
    await gateway.start()
    timeout = settings.gateway_apply_timeout_seconds
    async with sessions() as session:
        repository = ConfigurationRepository(session)
        for item in resolved:
            if item.source is ConfigurationSource.DATABASE:
                result = await gateway.confirm_ready(
                    item.device_id, version=item.version, timeout_seconds=timeout
                )
                apply_status = ApplyStatus.APPLIED if result.applied else ApplyStatus.FAILED
            else:
                result = None
                apply_status = ApplyStatus.PENDING
            await repository.upsert_runtime_status(
                device_id=item.device_id,
                desired_version=item.version,
                applied_version=item.version if (result and result.applied) else None,
                apply_status=apply_status,
                source=item.source,
                last_apply_at=datetime.now(UTC),
                last_apply_error=result.error if result is not None else None,
            )
        await session.commit()
    gateway.mark_loaded()
    logger.info(
        "gateway_managed_configuration_loaded",
        extra={
            "device_count": len(resolved),
            "managed_device_count": sum(
                1 for item in resolved if item.source is ConfigurationSource.DATABASE
            ),
            "bootstrap_device_count": sum(
                1 for item in resolved if item.source is ConfigurationSource.BOOTSTRAP
            ),
        },
    )
    return gateway


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    database = Database(settings)
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    websocket_manager = WebSocketManager(settings.websocket_queue_size)
    counters = IngestionCounters()
    diagnosis: OnlineDiagnosisCoordinator | None = None
    diagnosis_error: str | None = None
    knowledge_index: KnowledgeIndex | None = None
    knowledge_error: str | None = None
    workflow_service: WorkflowService | None = None
    workflow_error: str | None = None
    checkpoint_context: Any = None
    if settings.diagnosis_enabled:
        try:
            runtime = ModelRuntime.load(
                settings.diagnosis_artifact_path, settings.diagnosis_manifest_path
            )
            diagnosis = OnlineDiagnosisCoordinator(runtime, database.sessions)
            await diagnosis.warmup()
        except ModelCompatibilityError as exc:
            diagnosis_error = str(exc)
            logger.error("diagnosis_model_unavailable", extra={"error": diagnosis_error})
    if settings.knowledge_enabled:
        try:
            knowledge_index = KnowledgeIndex.load(settings.knowledge_index_path)
            if knowledge_index.artifact.corpus_version != settings.knowledge_corpus_version:
                raise ValueError("knowledge corpus version does not match configuration")
            if knowledge_index.artifact.embedding_model != settings.knowledge_embedding_version:
                raise ValueError("knowledge embedding version does not match configuration")
            logger.info(
                "knowledge_index_loaded",
                extra={
                    "corpus_version": knowledge_index.artifact.corpus_version,
                    "chunk_count": len(knowledge_index.chunks),
                },
            )
        except (OSError, ValueError) as exc:
            knowledge_error = str(exc)
            logger.error("knowledge_index_unavailable", extra={"error": knowledge_error})
    if settings.workflow_enabled:
        try:
            provider: AgentModelProvider
            if settings.agent_provider == "test":
                if settings.environment not in {"development", "test", "ci"}:
                    raise ValueError("test agent provider is forbidden outside test environments")
                provider = TestProvider()
            elif settings.agent_provider == "openai_compatible":
                if settings.agent_api_key is None or not settings.agent_model.strip():
                    raise ValueError(
                        "AGENT_API_KEY and AGENT_MODEL are required for the real provider"
                    )
                provider = OpenAICompatibleProvider(
                    api_key=settings.agent_api_key.get_secret_value(),
                    base_url=settings.agent_base_url,
                    model=settings.agent_model,
                    temperature=settings.agent_temperature,
                    timeout_seconds=settings.agent_timeout_seconds,
                    schema_max_attempts=settings.agent_schema_max_attempts,
                )
            else:
                raise ValueError(f"unsupported agent provider: {settings.agent_provider}")
            checkpoint_context = AsyncPostgresSaver.from_conn_string(
                settings.checkpoint_database_url
            )
            checkpointer = await checkpoint_context.__aenter__()
            workflow_service = WorkflowService(
                sessions=database.sessions,
                knowledge_index=knowledge_index,
                provider=provider,
                checkpointer=checkpointer,
                max_attempts=settings.agent_max_attempts,
                backoff_seconds=settings.agent_backoff_seconds,
                timeout_seconds=settings.agent_timeout_seconds,
            )
            if settings.observability_enabled:
                workflow_service = ObservableWorkflowService(
                    workflow_service, WorkflowTracer(database.sessions)
                )
        except Exception as exc:
            workflow_error = str(exc)
            logger.error("workflow_service_unavailable", extra={"error": workflow_error})
    mqtt = MqttTelemetryConsumer(
        settings, database.sessions, redis, websocket_manager, counters, diagnosis
    )
    gateway: IndustrialProtocolGateway | None = None
    gateway_error: str | None = None
    if settings.gateway_enabled:
        policy = RetryPolicy(
            failure_threshold=settings.gateway_failure_threshold,
            reconnect_threshold=settings.gateway_reconnect_threshold,
            max_reconnect_attempts=settings.gateway_max_reconnect_attempts,
            backoff_initial_seconds=settings.gateway_backoff_initial_seconds,
            backoff_max_seconds=settings.gateway_backoff_max_seconds,
        )
        sink = GatewayIngestionSink(
            database.sessions, redis, websocket_manager, counters, diagnosis
        )
        registration = DeviceRegistrationChecker(database.sessions)
        simulator_source = build_simulator_source_factory()
        if settings.config_management_enabled:
            gateway = await _build_managed_gateway(
                sessions=database.sessions,
                policy=policy,
                sink=sink,
                registration=registration,
                simulator_source=simulator_source,
                mqtt_connected=lambda: mqtt.connected,
            )
        else:
            try:
                gateway = IndustrialProtocolGateway.from_config_file(
                    settings.gateway_config_path,
                    sink=sink,
                    registration=registration,
                    policy=policy,
                    simulator_source_factory=simulator_source,
                    mqtt_connected=lambda: mqtt.connected,
                )
            except GatewayConfigurationError as exc:
                gateway_error = str(exc)
                logger.error("gateway_unavailable", extra={"error": gateway_error})
    app.state.configuration_applier = (
        GatewayDefinitionApplier(gateway) if gateway is not None else UnavailableApplier()
    )
    app.state.database = database
    app.state.redis = redis
    app.state.websocket_manager = websocket_manager
    app.state.ingestion_counters = counters
    app.state.mqtt = mqtt
    app.state.diagnosis = diagnosis
    app.state.diagnosis_error = diagnosis_error
    app.state.knowledge_index = knowledge_index
    app.state.knowledge_error = knowledge_error
    app.state.workflow_service = workflow_service
    app.state.workflow_error = workflow_error
    app.state.gateway = gateway
    app.state.gateway_enabled = settings.gateway_enabled
    app.state.gateway_error = gateway_error
    if settings.mqtt_enabled:
        mqtt.start()
    if gateway is not None and not settings.config_management_enabled:
        await gateway.start()
    try:
        yield
    finally:
        if gateway is not None:
            await gateway.stop()
        await mqtt.stop()
        if checkpoint_context is not None:
            await checkpoint_context.__aexit__(None, None, None)
        await redis.aclose()
        await database.close()


app = FastAPI(
    title="Industrial AI Control Tower",
    version="0.4.0",
    description=(
        "Industrial telemetry, synthetic-benchmark ML diagnosis, and cited knowledge retrieval."
    ),
    lifespan=lifespan,
)
app.include_router(devices.router)
app.include_router(telemetry.router)
app.include_router(alarms.router, prefix="/api/v1")
app.include_router(alarms.router, prefix="/api")
app.include_router(alarm_rules.router, prefix="/api/v1")
app.include_router(alarm_rules.router, prefix="/api")
app.include_router(diagnoses.router)
app.include_router(knowledge.router)
app.include_router(workflows.router)
app.include_router(observability.router, prefix="/api/v1")
app.include_router(observability.router, prefix="/api")
app.include_router(connectivity.router, prefix="/api/v1")
app.include_router(connectivity.router, prefix="/api")
app.include_router(assets.router, prefix="/api/v1")
app.include_router(assets.router, prefix="/api")
app.include_router(configurations.router, prefix="/api/v1")
app.include_router(configurations.router, prefix="/api")
app.include_router(websockets.router)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next: Any) -> Any:
    trace_id = request.headers.get("X-Trace-ID") or str(uuid4())
    token = trace_id_context.set(trace_id)
    try:
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response
    finally:
        trace_id_context.reset(token)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return _error_response(
        exc.code, exc.message, trace_id_context.get(), exc.status_code, exc.details
    )


@app.exception_handler(AssetConfigError)
async def asset_config_error_handler(request: Request, exc: AssetConfigError) -> JSONResponse:
    return _error_response(
        exc.code, exc.message, trace_id_context.get(), exc.status_code, exc.details
    )


@app.exception_handler(AlarmLifecycleError)
async def alarm_lifecycle_error_handler(request: Request, exc: AlarmLifecycleError) -> JSONResponse:
    return _error_response(
        exc.code, exc.message, trace_id_context.get(), exc.status_code, exc.details
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error_response(
        "VALIDATION_ERROR", "Request validation failed.", trace_id_context.get(), 422
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _error_response("HTTP_ERROR", str(exc.detail), trace_id_context.get(), exc.status_code)


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_request_error")
    return _error_response(
        "INTERNAL_ERROR", "An internal error occurred.", trace_id_context.get(), 500
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready(request: Request) -> JSONResponse:
    dependencies: dict[str, str] = {}
    try:
        async with request.app.state.database.sessions() as session:
            await session.execute(text("SELECT 1"))
        dependencies["postgres"] = "ok"
    except Exception:
        dependencies["postgres"] = "unavailable"
    try:
        await request.app.state.redis.ping()
        dependencies["redis"] = "ok"
    except Exception:
        dependencies["redis"] = "unavailable"
    dependencies["mqtt"] = "connected" if request.app.state.mqtt.connected else "degraded"
    if settings.diagnosis_enabled:
        dependencies["diagnosis"] = (
            "loaded" if request.app.state.diagnosis is not None else "unavailable"
        )
    else:
        dependencies["diagnosis"] = "disabled"
    if settings.knowledge_enabled:
        dependencies["knowledge"] = (
            "indexed" if request.app.state.knowledge_index is not None else "unavailable"
        )
    else:
        dependencies["knowledge"] = "disabled"
    if settings.workflow_enabled:
        dependencies["workflow"] = (
            "available" if request.app.state.workflow_service is not None else "unavailable"
        )
    else:
        dependencies["workflow"] = "disabled"
    dependencies["observability"] = "enabled" if settings.observability_enabled else "disabled"
    dependencies["configuration"] = "enabled" if settings.config_management_enabled else "disabled"
    if settings.gateway_enabled:
        dependencies["connectivity"] = (
            "available" if request.app.state.gateway is not None else "unavailable"
        )
    else:
        dependencies["connectivity"] = "disabled"
    ready_state = all(dependencies[name] == "ok" for name in ("postgres", "redis"))
    if settings.diagnosis_enabled:
        ready_state = ready_state and dependencies["diagnosis"] == "loaded"
    if settings.knowledge_enabled:
        ready_state = ready_state and dependencies["knowledge"] == "indexed"
    if settings.workflow_enabled:
        ready_state = ready_state and dependencies["workflow"] == "available"
    if settings.gateway_enabled:
        ready_state = ready_state and dependencies["connectivity"] == "available"
    return JSONResponse(
        status_code=200 if ready_state else 503,
        content={"status": "ready" if ready_state else "not_ready", "dependencies": dependencies},
    )
