"""Shared fixtures for alarm lifecycle and incident correlation tests.

Half of what Phase 6.9-A promises is enforced by the database rather than by
application code. The open-instance invariant is a partial unique index, the
status vocabulary is a check constraint, and the recurrence semantics depend on
the index predicate. A fake repository cannot prove any of that, so a real
PostgreSQL server is used.

The suite is opt-in. It is skipped unless ``ALARM_TEST_DATABASE_URL`` names a
throwaway database matching the test-only guard, so a run without PostgreSQL
stays green and a live database is never touched.

Example invocation::

    export ALARM_TEST_DATABASE_URL="postgresql+asyncpg://postgres:<pw>@localhost:5432/alarm_phase69_test"
    pytest tests/incidents -q

Only the tables this package needs are created. The knowledge tables carry a
pgvector column and are deliberately left out, so the fixture does not depend on
the vector extension.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator, Iterator
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

from app.assetconfig.models import AssetNode
from app.incidents.models import AlarmRule, IncidentAlarm
from app.models import (
    Alarm,
    Approval,
    AuditEvent,
    Device,
    Diagnosis,
    Incident,
    MaintenancePlan,
    Telemetry,
)
from app.models import WorkflowRun as WorkflowRunModel

TEST_DATABASE_ENV = "ALARM_TEST_DATABASE_URL"
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
    # AssetNode precedes Device because devices.asset_node_id holds a foreign key
    # to it, and create_all trusts the caller to order the list correctly.
    return [
        AssetNode.__table__,
        Device.__table__,
        Telemetry.__table__,
        Alarm.__table__,
        AlarmRule.__table__,
        Incident.__table__,
        Diagnosis.__table__,
        IncidentAlarm.__table__,
        AuditEvent.__table__,
        # Phase 6.9-C: workflow bridge and gate tests need the run and approval
        # tables. approvals.maintenance_plan_id references maintenance_plans, so
        # the plan table is created too even though no test writes a plan row.
        # WorkOrder is deliberately left out — the gate tests never reach it.
        WorkflowRunModel.__table__,
        MaintenancePlan.__table__,
        Approval.__table__,
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

    Provisioning runs in its own event loop and its own engine, so no asyncpg
    connection outlives the loop that opened it.
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
    """Yield a session factory, for code and routes that open their own sessions."""

    await _truncate(db_engine)
    yield async_sessionmaker(db_engine, expire_on_commit=False)


async def create_device(
    session: AsyncSession,
    device_id: str,
    *,
    device_type: str = "MOTOR",
    status: str = "ACTIVE",
) -> Device:
    """Insert one device master row."""

    device = Device(
        device_id=device_id,
        device_type=device_type,
        name=device_id,
        status=status,
        device_metadata={},
    )
    session.add(device)
    await session.flush()
    return device


async def seed_rule(
    session: AsyncSession,
    rule_id: str = "temperature_high",
    *,
    name: str = "High temperature",
    signal_name: str = "temperature",
    operator: str = "GT",
    threshold: float = 90.0,
    severity: str = "CRITICAL",
    priority: str = "URGENT",
    enabled: bool = True,
    device_type: str | None = None,
) -> AlarmRule:
    """Insert one alarm rule."""

    rule = AlarmRule(
        id=rule_id,
        name=name,
        description="",
        device_type=device_type,
        signal_name=signal_name,
        operator=operator,
        threshold=threshold,
        severity=severity,
        priority=priority,
        enabled=enabled,
    )
    session.add(rule)
    await session.flush()
    return rule


def telemetry_payload(
    device_id: str = "MOTOR-001",
    *,
    timestamp: datetime | None = None,
    temperature_c: float = 60.0,
    vibration_mm_s: float = 1.0,
    bearing_temperature_c: float = 45.0,
    current_a: float = 12.0,
    voltage_v: float = 400.0,
    rpm: int = 1480,
    load_pct: float = 55.0,
    power_kw: float = 7.5,
    operating_state: str = "RUNNING",
    fault_state: str = "NORMAL",
) -> dict[str, Any]:
    """Return a fully covered telemetry payload."""

    moment = timestamp or utc(2026, 9, 23, 10, 0, 0)
    return {
        "schema_version": "1.0",
        "timestamp": moment.isoformat(),
        "device_id": device_id,
        "temperature_c": temperature_c,
        "bearing_temperature_c": bearing_temperature_c,
        "vibration_mm_s": vibration_mm_s,
        "current_a": current_a,
        "voltage_v": voltage_v,
        "rpm": rpm,
        "load_pct": load_pct,
        "power_kw": power_kw,
        "operating_state": operating_state,
        "fault_state": fault_state,
    }


def utc(
    year: int = 2026,
    month: int = 9,
    day: int = 23,
    hour: int = 10,
    minute: int = 0,
    second: int = 0,
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)
