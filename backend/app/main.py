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

from app.api import alarms, devices, telemetry, websockets
from app.config import get_settings
from app.core.context import trace_id_context
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.infrastructure.database.session import Database
from app.infrastructure.mqtt.consumer import MqttTelemetryConsumer
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
    mqtt = MqttTelemetryConsumer(settings, database.sessions, redis, websocket_manager, counters)
    app.state.database = database
    app.state.redis = redis
    app.state.websocket_manager = websocket_manager
    app.state.ingestion_counters = counters
    app.state.mqtt = mqtt
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
    version="0.2.0",
    description="Phase 2 backend and industrial telemetry data platform.",
    lifespan=lifespan,
)
app.include_router(devices.router)
app.include_router(telemetry.router)
app.include_router(alarms.router)
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
    ready_state = all(dependencies[name] == "ok" for name in ("postgres", "redis"))
    return JSONResponse(
        status_code=200 if ready_state else 503,
        content={"status": "ready" if ready_state else "not_ready", "dependencies": dependencies},
    )
