"""Phase 6.10 platform reliability tests: health, recovery, metrics.

These tests run without a database. The readiness endpoint is exercised
against stubbed ``app.state`` dependencies; the retry policy is exercised
directly with a recording sleep. Data-reliability tests that need PostgreSQL
live in ``tests/incidents/test_platform_reliability.py``.
"""

import asyncio
import contextlib
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.main import app, settings
from app.platform_observability.resilience import (
    AsyncRetry,
    RetryExhaustedError,
    default_database_retry,
)
from app.platform_observability.tasks import monitor_background_task

REQUIRED_METRIC_NAMES = (
    "adapter_connect_success_total",
    "adapter_connect_failure_total",
    "adapter_read_latency_seconds",
    "adapter_last_success_timestamp",
    "telemetry_ingest_total",
    "telemetry_ingest_failed_total",
    "telemetry_processing_latency_seconds",
    "alarm_created_total",
    "alarm_cleared_total",
    "alarm_active_count",
    "incident_created_total",
    "incident_resolved_total",
    "incident_active_count",
    "workflow_started_total",
    "workflow_waiting_approval_total",
    "workflow_failed_total",
    "mqtt_reconnect_total",
    "background_task_failure_total",
)


def _clear_stubs() -> None:
    with contextlib.suppress(AttributeError):
        for attribute in (
            "database",
            "redis",
            "mqtt",
            "diagnosis",
            "knowledge_index",
            "workflow_service",
            "gateway",
        ):
            delattr(app.state, attribute)


# --------------------------------------------------------------------------- #
# Stubs for readiness dependencies
# --------------------------------------------------------------------------- #


class FakeDatabase:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def sessions(self) -> Any:
        if self.fail:
            raise RuntimeError("database is down")
        return _NullSessionContext()


class _NullSessionContext:
    async def __aenter__(self) -> Any:
        return _NullSession()

    async def __aexit__(self, *args: Any) -> None:
        return None


class _NullSession:
    async def execute(self, statement: Any) -> None:
        return None


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def ping(self) -> bool:
        if self.fail:
            raise RuntimeError("redis is down")
        return True


class FakeMqtt:
    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected


@pytest.fixture()
def stub_dependencies(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Deterministic readiness inputs: every optional feature disabled."""

    monkeypatch.setattr(settings, "diagnosis_enabled", False, raising=False)
    monkeypatch.setattr(settings, "knowledge_enabled", False, raising=False)
    monkeypatch.setattr(settings, "workflow_enabled", False, raising=False)
    monkeypatch.setattr(settings, "gateway_enabled", False, raising=False)
    monkeypatch.setattr(settings, "observability_enabled", False, raising=False)
    monkeypatch.setattr(settings, "config_management_enabled", False, raising=False)
    app.state.database = FakeDatabase()
    app.state.redis = FakeRedis()
    app.state.mqtt = FakeMqtt(connected=True)
    app.state.diagnosis = None
    app.state.knowledge_index = None
    app.state.workflow_service = object()
    app.state.gateway = None
    yield
    _clear_stubs()


@pytest.fixture()
def fast_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero-delay database retry so readiness tests stay fast."""

    monkeypatch.setattr(
        "app.main.default_database_retry",
        lambda: AsyncRetry(max_attempts=3, delays=(0.0, 0.0)),
    )


# --------------------------------------------------------------------------- #
# Health & readiness
# --------------------------------------------------------------------------- #


def test_health_stays_lightweight() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_all_dependencies_ok(stub_dependencies: None, fast_retry: None) -> None:
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {
        "database": "ok",
        "redis": "ok",
        "mqtt": "connected",
        "model": "disabled",
    }


def test_ready_reports_database_unavailable(stub_dependencies: None, fast_retry: None) -> None:
    app.state.database = FakeDatabase(fail=True)
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database"] == "unavailable"
    assert body["checks"]["redis"] == "ok"


def test_ready_reports_redis_unavailable(stub_dependencies: None, fast_retry: None) -> None:
    app.state.redis = FakeRedis(fail=True)
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["redis"] == "unavailable"


def test_ready_reports_mqtt_degraded_but_stays_ready(
    stub_dependencies: None, fast_retry: None
) -> None:
    """MQTT degradation is visible but does not flip readiness by itself."""

    app.state.mqtt = FakeMqtt(connected=False)
    client = TestClient(app)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["mqtt"] == "degraded"


# --------------------------------------------------------------------------- #
# Recovery: bounded database retry
# --------------------------------------------------------------------------- #


class RecordingSleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)


async def test_retry_succeeds_after_transient_failures() -> None:
    sleeper = RecordingSleeper()
    retry = AsyncRetry(max_attempts=3, delays=(1.0, 2.0, 4.0), sleep=sleeper.sleep)
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("transient")
        return "ok"

    assert await retry.run(flaky) == "ok"
    assert attempts == 3
    assert sleeper.delays == [1.0, 2.0]


async def test_retry_exhausts_and_raises() -> None:
    sleeper = RecordingSleeper()
    retry = AsyncRetry(max_attempts=3, delays=(1.0, 2.0, 4.0), sleep=sleeper.sleep)
    attempts = 0

    async def always_fails() -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("still down")

    with pytest.raises(RetryExhaustedError) as excinfo:
        await retry.run(always_fails)
    assert excinfo.value.attempts == 3
    assert attempts == 3
    assert sleeper.delays == [1.0, 2.0]


async def test_retry_does_not_retry_unexpected_exceptions() -> None:
    sleeper = RecordingSleeper()
    retry = AsyncRetry(
        max_attempts=3, delays=(1.0, 2.0), exceptions=(RuntimeError,), sleep=sleeper.sleep
    )
    attempts = 0

    async def wrong_kind() -> None:
        nonlocal attempts
        attempts += 1
        raise ValueError("programmer error")

    with pytest.raises(ValueError):
        await retry.run(wrong_kind)
    assert attempts == 1
    assert sleeper.delays == []


def test_default_database_retry_matches_phase_policy() -> None:
    retry = default_database_retry()
    assert retry.max_attempts == 3
    assert retry.delays == (1.0, 2.0, 4.0)


# --------------------------------------------------------------------------- #
# Background task reliability
# --------------------------------------------------------------------------- #


async def test_failing_background_task_is_counted_not_silent() -> None:
    async def explode() -> None:
        raise RuntimeError("background task crashed")

    def failures_for(task_name: str) -> float:
        return (
            REGISTRY.get_sample_value("background_task_failure_total", {"task": task_name}) or 0.0
        )

    before = failures_for("test-crashing-task")
    task = monitor_background_task(asyncio.create_task(explode()), name="test-crashing-task")
    with pytest.raises(RuntimeError):
        await task
    await asyncio.sleep(0)  # let the done-callback run
    assert failures_for("test-crashing-task") == before + 1


# --------------------------------------------------------------------------- #
# Prometheus exposition
# --------------------------------------------------------------------------- #


def test_metrics_endpoint_returns_prometheus_format() -> None:
    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    for name in REQUIRED_METRIC_NAMES:
        assert name in body, f"missing metric: {name}"


def test_metrics_endpoint_survives_database_failure(
    stub_dependencies: None,
) -> None:
    """The exposition must not die with the database."""

    app.state.database = FakeDatabase(fail=True)
    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "telemetry_ingest_total" in response.text


# --------------------------------------------------------------------------- #
# Platform metrics API
# --------------------------------------------------------------------------- #


class CountingSession:
    async def scalar(self, statement: Any) -> int:
        return 7


def test_platform_metrics_api_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.dependencies import get_session
    from app.services.telemetry import IngestionCounters

    async def override_session() -> Any:
        yield CountingSession()

    app.dependency_overrides[get_session] = override_session
    app.state.process_started_monotonic = time.monotonic() - 100.0
    counters = IngestionCounters()
    counters.persisted = 1000
    app.state.ingestion_counters = counters
    try:
        client = TestClient(app)
        response = client.get("/api/v1/platform/metrics")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"system", "pipeline", "incident"}
        assert body["system"]["uptime_seconds"] == pytest.approx(100.0, abs=1.0)
        assert body["pipeline"]["telemetry_rate"] == pytest.approx(10.0, abs=0.2)
        assert body["incident"]["active"] == 7
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Ordering guard (no-DB): latest timestamp wins in the latest-only cache
# is covered DB-free in tests/test_cache_and_websocket.py; the ingestion-level
# guarantee is covered in tests/incidents/test_platform_reliability.py.
# --------------------------------------------------------------------------- #


def test_readiness_database_probe_uses_bounded_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The readiness probe retries a transient database blip, then gives up."""

    calls = 0

    class FlakyDatabase:
        def __init__(self) -> None:
            self.fail_until = 0

        def sessions(self) -> Any:
            nonlocal calls
            calls += 1
            if calls <= self.fail_until:
                raise RuntimeError("database is down")
            return _NullSessionContext()

    monkeypatch.setattr(settings, "diagnosis_enabled", False, raising=False)
    monkeypatch.setattr(settings, "knowledge_enabled", False, raising=False)
    monkeypatch.setattr(settings, "workflow_enabled", False, raising=False)
    monkeypatch.setattr(settings, "gateway_enabled", False, raising=False)
    monkeypatch.setattr(settings, "observability_enabled", False, raising=False)
    monkeypatch.setattr(settings, "config_management_enabled", False, raising=False)
    app.state.redis = FakeRedis()
    app.state.mqtt = FakeMqtt(connected=True)
    app.state.diagnosis = None
    app.state.knowledge_index = None
    app.state.workflow_service = object()
    app.state.gateway = None
    database = FlakyDatabase()
    database.fail_until = 2  # fails twice, succeeds on the third attempt
    app.state.database = database
    try:
        client = TestClient(app)
        response = client.get("/ready")
        assert response.status_code == 200
        assert calls == 3
    finally:
        _clear_stubs()
