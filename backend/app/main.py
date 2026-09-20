"""FastAPI application entry point and managed infrastructure lifecycle."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import alarms, devices, diagnoses, knowledge, telemetry, websockets
from app.config import get_settings
from app.core.context import trace_id_context
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.infrastructure.database.session import Database
from app.infrastructure.mqtt.consumer import MqttTelemetryConsumer
from app.knowledge.retrieval import KnowledgeIndex
from app.ml.runtime import ModelCompatibilityError, ModelRuntime
from app.services.diagnosis import OnlineDiagnosisCoordinator
from app.services.telemetry import IngestionCounters
from app.websocket.manager import WebSocketManager

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


def _error_response(code: str, message: str, trace_id: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "trace_id": trace_id}},
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database = Database(settings)
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    websocket_manager = WebSocketManager(settings.websocket_queue_size)
    counters = IngestionCounters()
    diagnosis: OnlineDiagnosisCoordinator | None = None
    diagnosis_error: str | None = None
    knowledge_index: KnowledgeIndex | None = None
    knowledge_error: str | None = None
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
    mqtt = MqttTelemetryConsumer(
        settings, database.sessions, redis, websocket_manager, counters, diagnosis
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
    if settings.mqtt_enabled:
        mqtt.start()
    try:
        yield
    finally:
        await mqtt.stop()
        await redis.aclose()
        await database.close()


app = FastAPI(
    title="Industrial AI Control Tower",
    version="0.3.0",
    description="Industrial telemetry platform with synthetic-benchmark ML diagnosis.",
    lifespan=lifespan,
)
app.include_router(devices.router)
app.include_router(telemetry.router)
app.include_router(alarms.router)
app.include_router(diagnoses.router)
app.include_router(knowledge.router)
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
    return _error_response(exc.code, exc.message, trace_id_context.get(), exc.status_code)


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
    ready_state = all(dependencies[name] == "ok" for name in ("postgres", "redis"))
    if settings.diagnosis_enabled:
        ready_state = ready_state and dependencies["diagnosis"] == "loaded"
    return JSONResponse(
        status_code=200 if ready_state else 503,
        content={"status": "ready" if ready_state else "not_ready", "dependencies": dependencies},
    )
