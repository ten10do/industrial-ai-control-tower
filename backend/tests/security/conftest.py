"""Fixtures for the Phase 6.12 security suite.

Half of what this phase promises is enforced by the database rather than by
application code: uniqueness of a username, the composite primary keys that make
a duplicate grant impossible, the status check constraint. A fake repository
cannot demonstrate any of that, so the tests that prove those properties run
against a real PostgreSQL.

The suite is opt-in in the same way as the alarm and incident suites: it is
skipped unless ``ALARM_TEST_DATABASE_URL`` names a throwaway database matching
the test-only guard. A run without PostgreSQL stays green, and a live database is
never touched.

Example invocation::

    export ALARM_TEST_DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/security_phase612_test"
    pytest tests/security -q
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.dependencies import get_session
from app.assetconfig.models import AssetNode
from app.config import get_settings
from app.incidents.models import AlarmRule, IncidentAlarm
from app.main import app
from app.models import (
    Alarm,
    Approval,
    AuditEvent,
    Device,
    Diagnosis,
    Incident,
    MaintenancePlan,
    Permission,
    Role,
    RolePermission,
    Telemetry,
    User,
    UserRole,
    WorkOrder,
)
from app.models import WorkflowRun as WorkflowRunModel
from app.security.dependencies import get_principal
from app.security.rbac import ROLE_PERMISSIONS, Principal

TEST_DATABASE_ENV = "ALARM_TEST_DATABASE_URL"
ADMIN_DATABASE = "postgres"
_SAFE_DATABASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*test[a-z0-9_]*$")

#: Signing secret for the suite. A test value, not a credential: it never leaves
#: this process, and it is long enough for HS256 so the suite does not emit
#: PyJWT's short-key warning and drown the real signals. The ``dummy-`` prefix is
#: deliberate: it is on the secret scanner's placeholder list, so this fixture is
#: not reported as a committed secret and the scanner's signal stays meaningful.
TEST_JWT_SECRET = "dummy-phase-6-12-signing-secret-for-hs256"

TEST_PASSWORD = "dummy-operator-password-for-tests"


def require_safe_database_name(url: str) -> str:
    """Return the target database name, or refuse before any statement runs."""

    name = make_url(url).database
    if not name or not _SAFE_DATABASE_PATTERN.match(name):
        raise RuntimeError(
            f"{TEST_DATABASE_ENV} must name a disposable test database matching "
            f"{_SAFE_DATABASE_PATTERN.pattern!r}; refusing to touch {name!r}."
        )
    return name


def _tables() -> list[Any]:
    """Return the tables this package needs, in dependency order.

    The knowledge tables are left out because ``knowledge_chunks`` carries a
    pgvector column and would make the fixture depend on the vector extension.
    """

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
        WorkflowRunModel.__table__,
        MaintenancePlan.__table__,
        Approval.__table__,
        WorkOrder.__table__,
        User.__table__,
        Role.__table__,
        Permission.__table__,
        UserRole.__table__,
        RolePermission.__table__,
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
def test_database_url() -> str:
    url = os.environ.get(TEST_DATABASE_ENV, "").strip()
    if not url:
        pytest.skip(f"{TEST_DATABASE_ENV} is not configured")
    require_safe_database_name(url)
    return url


@pytest.fixture(scope="session")
def provisioned_database(test_database_url: str) -> Iterator[str]:
    """Create the throwaway database and its schema once, then drop it."""

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


async def seed_roles(session: AsyncSession) -> None:
    """Insert the default roles, permissions, and grants.

    The migration seeds the same content in SQL. ``create_all`` only creates
    structure, so the fixture seeds it here from the code table, which is also
    what lets the vocabulary test assert that the migration and the code agree.
    """

    role_ids: dict[str, Any] = {}
    for name in ROLE_PERMISSIONS:
        role = Role(id=uuid4(), name=name, description="")
        session.add(role)
        role_ids[name] = role.id

    permission_names = sorted({grant for grants in ROLE_PERMISSIONS.values() for grant in grants})
    permission_ids: dict[str, Any] = {}
    for name in permission_names:
        permission = Permission(id=uuid4(), name=name, description="")
        session.add(permission)
        permission_ids[name] = permission.id
    await session.flush()

    for role_name, grants in ROLE_PERMISSIONS.items():
        for grant in grants:
            session.add(
                RolePermission(role_id=role_ids[role_name], permission_id=permission_ids[grant])
            )
    await session.flush()


@pytest_asyncio.fixture
async def session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Yield a session against an empty database with the roles seeded."""

    await _truncate(db_engine)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        await seed_roles(session)
        await session.commit()
        yield session


@pytest_asyncio.fixture
async def sessions(db_engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Yield a session factory, for code and routes that open their own sessions."""

    await _truncate(db_engine)
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as seed_session:
        await seed_roles(seed_session)
        await seed_session.commit()
    yield factory


@pytest.fixture(scope="session", autouse=True)
def signing_secret() -> Iterator[None]:
    """Configure the token signing secret for the whole suite."""

    previous = os.environ.get("SECURITY_JWT_SECRET")
    os.environ["SECURITY_JWT_SECRET"] = TEST_JWT_SECRET
    get_settings.cache_clear()
    yield
    if previous is None:
        os.environ.pop("SECURITY_JWT_SECRET", None)
    else:
        os.environ["SECURITY_JWT_SECRET"] = previous
    get_settings.cache_clear()


class RecordingCounterStore:
    """Minimal Redis stand-in: the three operations the limiter uses."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}

    async def get(self, name: str) -> bytes | None:
        value = self.counters.get(name)
        return None if value is None else str(value).encode()

    async def incr(self, name: str, amount: int = 1) -> int:
        self.counters[name] = self.counters.get(name, 0) + amount
        return self.counters[name]

    async def expire(self, name: str, time: int) -> bool:
        return True

    async def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            if self.counters.pop(name, None) is not None:
                removed += 1
        return removed


@pytest_asyncio.fixture
async def client(
    sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """An HTTP client against the real application, using the test database."""

    previous_redis = getattr(app.state, "redis", None)
    previous_workflow = getattr(app.state, "workflow_service", None)
    store = RecordingCounterStore()
    app.state.redis = store
    # The routes that delegate to the agent workflow read this attribute. The
    # lifespan is not started in tests, so it is set explicitly to the value the
    # lifespan would use when the capability is switched off: ``None``, which the
    # route turns into a 503 rather than an AttributeError.
    app.state.workflow_service = None

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_principal, None)
        app.state.redis = previous_redis
        app.state.workflow_service = previous_workflow


def admin_principal(username: str = "admin.principal") -> Principal:
    """A principal holding every permission, for tests that are not about RBAC."""

    from app.security.rbac import ALL_PERMISSIONS, WILDCARD

    return Principal(
        user_id=uuid4(),
        username=username,
        roles=("ADMIN",),
        permissions=frozenset({WILDCARD, *ALL_PERMISSIONS}),
    )
