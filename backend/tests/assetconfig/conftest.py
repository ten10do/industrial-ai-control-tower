"""Shared fixtures for asset and device configuration tests.

The database-backed tests need real PostgreSQL. Half of what this phase promises is
enforced by the database itself: the single-published partial unique index, the
version uniqueness constraint, the status check constraints, and the foreign key
delete rules. A fake repository cannot prove any of those, so a real server is used.

The suite is opt-in. It is skipped unless ``ASSETCONFIG_TEST_DATABASE_URL`` points
at a throwaway database whose name matches the test-only guard, so CI without
PostgreSQL stays green and the live database is never touched.

Example invocation::

    export ASSETCONFIG_TEST_DATABASE_URL="postgresql+asyncpg://postgres:<pw>@localhost:5432/assetconfig_phase68_test"
    pytest tests/assetconfig -q

Only the tables this phase needs are created. The knowledge tables carry a pgvector
column, so they are deliberately left out to keep the fixture independent of the
vector extension.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.assetconfig.apply import ApplyOutcome
from app.assetconfig.models import (
    AssetNode,
    DeviceConfiguration,
    DeviceConfigurationRuntimeStatus,
)
from app.gateway.models import CANONICAL_SIGNAL_FIELDS, DeviceDefinition
from app.models import Alarm, AuditEvent, Device, Telemetry

TEST_DATABASE_ENV = "ASSETCONFIG_TEST_DATABASE_URL"
ADMIN_DATABASE = "postgres"
_SAFE_DATABASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*test[a-z0-9_]*$")


def require_safe_database_name(url: str) -> str:
    """Return the target database name, or refuse before any statement runs."""

    name = make_url(url).database
    if not name or not _SAFE_DATABASE_PATTERN.match(name):
        raise RuntimeError(
            f"{TEST_DATABASE_ENV} must name a disposable test database matching "
            f"{_SAFE_DATABASE_PATTERN.pattern!r}; refusing to touch {name!r}."
        )
    return name


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get(TEST_DATABASE_ENV, "").strip()
    if not url:
        pytest.skip(f"{TEST_DATABASE_ENV} is not configured")
    require_safe_database_name(url)
    return url


def _tables() -> list[Any]:
    return [
        Device.__table__,
        AssetNode.__table__,
        DeviceConfiguration.__table__,
        DeviceConfigurationRuntimeStatus.__table__,
        AuditEvent.__table__,
        Telemetry.__table__,
        Alarm.__table__,
    ]


async def _admin_execute(url: str, statements: list[tuple[str, dict[str, Any]]]) -> None:
    engine = create_async_engine(
        make_url(url).set(database=ADMIN_DATABASE), isolation_level="AUTOCOMMIT"
    )
    try:
        async with engine.connect() as connection:
            for statement, parameters in statements:
                await connection.execute(text(statement), parameters)
    finally:
        await engine.dispose()


async def _create_schema(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            from app.infrastructure.database.base import Base

            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=_tables()))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def provisioned_database(test_database_url: str) -> Iterator[str]:
    """Create the throwaway database and its schema once, then drop it.

    Database provisioning runs in its own event loop and its own engine, so no
    asyncpg connection outlives the loop that opened it. Each test then builds a
    fresh engine inside its own loop, which is why the engine fixture below is
    function scoped.
    """

    name = require_safe_database_name(test_database_url)
    terminate = (
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = :name AND pid <> pg_backend_pid()",
        {"name": name},
    )
    asyncio.run(
        _admin_execute(
            test_database_url,
            [
                terminate,
                (f'DROP DATABASE IF EXISTS "{name}"', {}),
                (f'CREATE DATABASE "{name}"', {}),
            ],
        )
    )
    asyncio.run(_create_schema(test_database_url))
    try:
        yield test_database_url
    finally:
        asyncio.run(
            _admin_execute(
                test_database_url,
                [terminate, (f'DROP DATABASE IF EXISTS "{name}"', {})],
            )
        )


@pytest_asyncio.fixture
async def db_engine(provisioned_database: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(provisioned_database)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _truncate(engine: AsyncEngine) -> None:
    tables = ", ".join(f'"{table.name}"' for table in _tables())
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest_asyncio.fixture
async def session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Yield a session against an empty database."""

    await _truncate(db_engine)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture
async def sessions(db_engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a session factory, for code that opens its own sessions."""

    await _truncate(db_engine)
    yield async_sessionmaker(db_engine, expire_on_commit=False)


async def create_device(
    session: AsyncSession, device_id: str, *, status: str = "ACTIVE", name: str | None = None
) -> Device:
    """Insert one device master row."""

    device = Device(
        device_id=device_id,
        device_type="MOTOR",
        name=name or device_id,
        status=status,
        device_metadata={},
    )
    session.add(device)
    await session.flush()
    return device


def modbus_payload(
    device_id: str = "MOTOR-001",
    *,
    host: str = "localhost",
    port: int = 5020,
    enabled: bool = True,
    poll_interval_ms: int = 1000,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a fully covered Modbus TCP definition payload."""

    registers = {
        signal: {"address": 40001 + index, "scale": 1.0, "unit": None}
        for index, signal in enumerate(CANONICAL_SIGNAL_FIELDS)
    }
    payload: dict[str, Any] = {
        "device_id": device_id,
        "protocol": "modbus_tcp",
        "enabled": enabled,
        "poll_interval_ms": poll_interval_ms,
        "state": {"operating_state": "RUNNING", "fault_state": "NORMAL"},
        "modbus_tcp": {
            "host": host,
            "port": port,
            "unit_id": 1,
            "timeout_seconds": 3.0,
            "registers": registers,
        },
    }
    if extra:
        payload.update(extra)
    return payload


def opcua_payload(
    device_id: str = "MOTOR-003", *, endpoint: str = "opc.tcp://localhost:4840/x"
) -> dict[str, Any]:
    """Return a fully covered OPC UA definition payload."""

    nodes = {
        signal: {"node_id": f"ns=2;s={device_id}/{signal}"} for signal in CANONICAL_SIGNAL_FIELDS
    }
    return {
        "device_id": device_id,
        "protocol": "opc_ua",
        "enabled": True,
        "poll_interval_ms": 1000,
        "state": {"operating_state": "RUNNING", "fault_state": "NORMAL"},
        "opc_ua": {"endpoint": endpoint, "timeout_seconds": 4.0, "nodes": nodes},
    }


def definition_from(payload: dict[str, Any]) -> DeviceDefinition:
    return DeviceDefinition.model_validate(payload)


class FakeApplier:
    """Record apply attempts and report a configurable outcome.

    It implements the same ``DefinitionApplier`` protocol the gateway-backed applier
    implements, so the service logic under test is the production logic.
    """

    def __init__(
        self,
        *,
        available: bool = True,
        succeed: bool = True,
        error: str = "connection refused",
        runtime_state: str = "CONNECTED",
    ) -> None:
        self._available = available
        self._succeed = succeed
        self._error = error
        self._runtime_state = runtime_state
        self._raises: Exception | None = None
        self.calls: list[tuple[str, int | None]] = []
        self.applied: dict[str, int | None] = {}

    @property
    def available(self) -> bool:
        return self._available

    def fail_from_now_on(self, *, error: str = "connection refused") -> None:
        self._succeed = False
        self._raises = None
        self._error = error
        self._runtime_state = "ERROR"

    def raise_from_now_on(self, exc: Exception) -> None:
        """Make the applier blow up, to prove a raising runtime is contained."""

        self._raises = exc

    def succeed_from_now_on(self) -> None:
        self._succeed = True
        self._raises = None
        self._error = "connection refused"
        self._runtime_state = "CONNECTED"

    async def apply(self, definition: DeviceDefinition, *, version: int | None) -> ApplyOutcome:
        self.calls.append((definition.device_id, version))
        if self._raises is not None:
            raise self._raises
        if not self._available:
            return ApplyOutcome(False, None, "gateway runtime is not available in this process")
        if self._succeed:
            self.applied[definition.device_id] = version
            return ApplyOutcome(True, version, None, self._runtime_state)
        return ApplyOutcome(False, None, self._error, "ERROR")

    def applied_version(self, device_id: str) -> int | None:
        return self.applied.get(device_id)

    def runtime_state(self, device_id: str) -> str | None:
        if device_id in self.applied:
            return self._runtime_state
        return None


@pytest.fixture
def fake_applier() -> Callable[..., FakeApplier]:
    return FakeApplier


class BlockingApplier(FakeApplier):
    """An applier that parks inside ``apply`` until the test releases it.

    It exists to make the transient APPLYING state observable: the attempt must be
    recorded before the runtime is touched, so a concurrent reader can see it.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def apply(self, definition: DeviceDefinition, *, version: int | None) -> ApplyOutcome:
        self.entered.set()
        await self.release.wait()
        return await super().apply(definition, version=version)


def utc(year: int = 2026, month: int = 9, day: int = 22) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)
