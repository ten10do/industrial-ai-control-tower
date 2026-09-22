# ruff: noqa: E402  (the simulator package is imported after a deliberate sys.path insert)
"""End-to-end integration: published configuration drives a real acquisition chain.

Nothing in this module is faked except the Redis latest-value cache, and that is
labelled where it appears. Everything else is the production path:

    device_configurations (PostgreSQL, published)
        -> resolve_definitions(managed=True)
        -> IndustrialProtocolGateway + DeviceRuntime
        -> real Modbus TCP / OPC UA adapter
        -> real simulator server on a real socket
        -> GatewayIngestionSink
        -> TelemetryService.ingest_payload
        -> telemetry row in PostgreSQL

The point is not that the parts work in isolation. It is that a version published
through the configuration service becomes the definition the runtime actually polls,
that the sample it polls arrives in the operational database unchanged, and that a bad
version cannot take a healthy runtime down.

The shipped simulators expose a five-signal subset, while the canonical contract
requires eight. Modbus reaches eight through explicit register scales. OPC UA node
mappings carry no scale, so the OPC UA ensemble is extended in place to eight nodes
before the server starts; the alternative would be binding eight signal names onto
five nodes and publishing physically absurd values.
"""

from __future__ import annotations

import asyncio
import socket
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assetconfig.apply import GatewayDefinitionApplier, UnavailableApplier
from app.assetconfig.models import ApplyStatus, ConfigurationSource
from app.assetconfig.service import ConfigurationService
from app.assetconfig.source import resolve_definitions
from app.gateway.gateway import IndustrialProtocolGateway
from app.gateway.ingestion import DeviceRegistrationChecker, GatewayIngestionSink
from app.gateway.models import CANONICAL_SIGNAL_FIELDS
from app.gateway.registry import DeviceRegistry
from app.gateway.runtime import RetryPolicy
from app.models import Alarm, Device, Telemetry
from app.services.telemetry import IngestionCounters
from app.websocket.manager import WebSocketManager
from tests.assetconfig.conftest import modbus_payload, opcua_payload

SIMULATOR_ROOT = Path(__file__).resolve().parents[3] / "simulator"
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from simulator.modbus import (  # type: ignore[import-not-found]
    ModbusTcpServerSimulator,
)
from simulator.opcua import (  # type: ignore[import-not-found]
    OpcUaServerSimulator,
)
from simulator.opcua import (
    nodes as opcua_nodes,
)

FAST = RetryPolicy(
    failure_threshold=2,
    reconnect_threshold=3,
    max_reconnect_attempts=1,
    backoff_initial_seconds=0.01,
    backoff_max_seconds=0.05,
)

POLL_MS = 150
APPLY_TIMEOUT = 5.0
NO_YAML = Path("phase-6-8-intentionally-absent.yaml")

# The Modbus simulator serves holding registers 40001..40005 with values
# [685, 1240, 710, 1480, 720]. The eight canonical signals are bound to those five
# addresses with explicit scales, chosen so every published value is plausible and
# sits below the alarm thresholds.
MODBUS_REGISTER_MAP: dict[str, dict[str, Any]] = {
    "temperature": {"address": 40001, "scale": 0.1, "unit": "C"},
    "bearing_temperature": {"address": 40002, "scale": 0.05, "unit": "C"},
    "vibration": {"address": 40003, "scale": 0.005, "unit": "mm/s"},
    "current": {"address": 40004, "scale": 0.01, "unit": "A"},
    "voltage": {"address": 40005, "scale": 0.5, "unit": "V"},
    "rpm": {"address": 40002, "scale": 1.0, "unit": "rpm"},
    "load": {"address": 40003, "scale": 0.1, "unit": "%"},
    "power": {"address": 40001, "scale": 0.01, "unit": "kW"},
}

MODBUS_EXPECTED: dict[str, float] = {
    "temperature_c": 685 * 0.1,
    "bearing_temperature_c": 1240 * 0.05,
    "vibration_mm_s": 710 * 0.005,
    "current_a": 1480 * 0.01,
    "voltage_v": 720 * 0.5,
    "rpm": 1240,
    "load_pct": 710 * 0.1,
    "power_kw": 685 * 0.01,
}

# One OPC UA node per canonical signal, so the mapping is a clean one to one.
OPCUA_ENSEMBLE: dict[str, float | int] = {
    "temperature": 68.2,
    "bearing_temperature": 62.4,
    "vibration": 3.1,
    "current": 12.4,
    "voltage": 380.0,
    "rpm": 1480,
    "load": 72.0,
    "power": 6.2,
}


class FakeLatestCache:
    """Stand-in for Redis, mirroring ``LatestTelemetryCache``'s Lua semantics.

    The subject of these tests is the acquisition chain and what lands in PostgreSQL.
    The Redis latest-value cache is peripheral and is covered by its own tests, so it
    is replaced rather than requiring a broker for an end-to-end run.
    """

    def __init__(self) -> None:
        self._rows: dict[str, tuple[float, str]] = {}

    async def eval(self, _script: str, _count: int, key: str, ts: float, payload: str) -> int:
        existing = self._rows.get(key)
        if existing is not None and existing[0] >= float(ts):
            return 0
        self._rows[key] = (float(ts), payload)
        return 1

    async def hget(self, key: str, field: str) -> bytes | None:
        row = self._rows.get(key)
        if row is None or field != "payload":
            return None
        return row[1].encode("utf-8")


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _opcua_endpoint() -> str:
    return f"opc.tcp://127.0.0.1:{_free_port()}/industrial-ai/integration/"


def _extend_opcua_ensemble(monkeypatch: pytest.MonkeyPatch) -> None:
    """Add the missing canonical signals to the simulator's node ensemble in place.

    ``node_identifier`` and ``OpcUaServerSimulator`` read the same dict objects, so
    mutating them keeps the advertised node ids and the served nodes consistent.
    """

    for signal, value in OPCUA_ENSEMBLE.items():
        monkeypatch.setitem(opcua_nodes.NODE_BROWSE_NAMES, signal, signal.replace("_", " ").title())
        monkeypatch.setitem(opcua_nodes.DETERMINISTIC_VALUES, signal, value)


@pytest.fixture
async def modbus_server() -> AsyncIterator[ModbusTcpServerSimulator]:
    server = ModbusTcpServerSimulator(host="127.0.0.1", port=_free_port())
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


def _modbus_config(device_id: str, port: int, **overrides: Any) -> dict[str, Any]:
    payload = modbus_payload(device_id, port=port, poll_interval_ms=POLL_MS)
    payload["modbus_tcp"]["registers"] = MODBUS_REGISTER_MAP
    payload.update(overrides)
    return payload


async def _seed_device(
    sessions: async_sessionmaker[AsyncSession], device_id: str, *, status: str = "ACTIVE"
) -> None:
    async with sessions() as session:
        session.add(
            Device(
                device_id=device_id,
                device_type="MOTOR",
                name=device_id,
                status=status,
                device_metadata={},
            )
        )
        await session.commit()


async def _publish(
    sessions: async_sessionmaker[AsyncSession], device_id: str, payload: dict[str, Any]
) -> int:
    """Publish a configuration through the service, exactly as the API would.

    ``UnavailableApplier`` stands in for the request-time runtime owner, because in
    this test the gateway is built afterwards and at process scope. Using a
    success-reporting fake here would write an APPLIED claim into the runtime status
    for a runtime that had not started, which is precisely the dishonesty this phase
    exists to prevent.
    """

    async with sessions() as session:
        service = ConfigurationService(session, UnavailableApplier())
        draft = await service.create_draft(device_id, payload, "integration")
        await service.publish(device_id, draft.version, "integration")
        return draft.version


async def _resolve(sessions: async_sessionmaker[AsyncSession]) -> list[Any]:
    return await resolve_definitions(sessions=sessions, yaml_path=NO_YAML, managed=True)


class _Chain:
    """A gateway wired to real PostgreSQL ingestion."""

    def __init__(
        self,
        gateway: IndustrialProtocolGateway,
        counters: IngestionCounters,
        applier: GatewayDefinitionApplier,
    ) -> None:
        self.gateway = gateway
        self.counters = counters
        self.applier = applier


def _build_gateway(
    *,
    sessions: async_sessionmaker[AsyncSession],
    definitions: list[Any],
    cache: FakeLatestCache,
    counters: IngestionCounters,
) -> _Chain:
    registry = DeviceRegistry()
    registry.load([item.definition for item in definitions])
    sink = GatewayIngestionSink(
        sessions,
        cache,  # type: ignore[arg-type]  # implements the Redis methods used
        WebSocketManager(),
        counters,
    )
    gateway = IndustrialProtocolGateway(
        registry=registry,
        sink=sink,
        registration=DeviceRegistrationChecker(sessions),
        enabled=True,
        config_file="configuration-management",
        policy=FAST,
    )
    return _Chain(gateway, counters, GatewayDefinitionApplier(gateway))


async def _wait_for_telemetry(
    sessions: async_sessionmaker[AsyncSession], device_id: str, *, minimum: int = 2
) -> list[Telemetry]:
    from app.models import Telemetry as Model

    loop = asyncio.get_running_loop()
    deadline = loop.time() + 20.0
    while True:
        async with sessions() as session:
            rows = list(
                await session.scalars(
                    select(Model)
                    .where(Model.device_id == device_id)
                    .order_by(Model.ingested_at, Model.id)
                )
            )
        if len(rows) >= minimum:
            return rows
        if loop.time() > deadline:
            raise AssertionError(
                f"{device_id} produced {len(rows)} telemetry row(s) before the timeout"
            )
        await asyncio.sleep(0.05)


async def _count_telemetry(sessions: async_sessionmaker[AsyncSession], device_id: str) -> int:
    async with sessions() as session:
        return int(
            await session.scalar(
                select(func.count()).select_from(Telemetry).where(Telemetry.device_id == device_id)
            )
            or 0
        )


async def _count_alarms(sessions: async_sessionmaker[AsyncSession], device_id: str) -> int:
    async with sessions() as session:
        return int(
            await session.scalar(
                select(func.count()).select_from(Alarm).where(Alarm.device_id == device_id)
            )
            or 0
        )


def _assert_close(actual: float, expected: float) -> None:
    assert actual == pytest.approx(expected, rel=1e-9, abs=1e-9), (actual, expected)


# ---------------------------------------------------------------------------
# The published configuration becomes the definition that is polled
# ---------------------------------------------------------------------------


async def test_a_published_modbus_configuration_reaches_postgres(
    sessions: async_sessionmaker[AsyncSession],
    modbus_server: ModbusTcpServerSimulator,
) -> None:
    device_id = "MOTOR-001"
    await _seed_device(sessions, device_id)
    version = await _publish(sessions, device_id, _modbus_config(device_id, modbus_server.port))
    assert version == 1

    resolved = await _resolve(sessions)
    assert [(item.device_id, item.source, item.version) for item in resolved] == [
        (device_id, ConfigurationSource.DATABASE, 1)
    ]
    assert resolved[0].definition.modbus_tcp is not None
    assert resolved[0].definition.modbus_tcp.port == modbus_server.port

    chain = _build_gateway(
        sessions=sessions,
        definitions=resolved,
        cache=FakeLatestCache(),
        counters=IngestionCounters(),
    )
    try:
        await chain.gateway.start()
        applied = await chain.applier.apply(resolved[0].definition, version=version)
        assert applied.applied is True
        assert applied.runtime_state == "CONNECTED"
        assert chain.gateway.applied_version(device_id) == 1

        rows = await _wait_for_telemetry(sessions, device_id)
        first = rows[0]
        _assert_close(first.temperature_c, MODBUS_EXPECTED["temperature_c"])
        _assert_close(first.bearing_temperature_c, MODBUS_EXPECTED["bearing_temperature_c"])
        _assert_close(first.vibration_mm_s, MODBUS_EXPECTED["vibration_mm_s"])
        _assert_close(first.current_a, MODBUS_EXPECTED["current_a"])
        _assert_close(first.voltage_v, MODBUS_EXPECTED["voltage_v"])
        assert first.rpm == MODBUS_EXPECTED["rpm"]
        _assert_close(first.load_pct, MODBUS_EXPECTED["load_pct"])
        _assert_close(first.power_kw, MODBUS_EXPECTED["power_kw"])
        assert first.operating_state == "RUNNING"
        assert first.fault_state == "NORMAL"
        assert first.schema_version == "1.0"
        assert chain.counters.persisted >= 2
        assert chain.counters.rejected == 0
        # Real measurements, not saturated ones: nothing here crosses an alarm rule.
        assert await _count_alarms(sessions, device_id) == 0
    finally:
        await chain.gateway.stop()


async def test_a_published_opcua_configuration_reaches_postgres(
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_id = "MOTOR-003"
    _extend_opcua_ensemble(monkeypatch)
    await _seed_device(sessions, device_id)
    assert set(OPCUA_ENSEMBLE) == set(CANONICAL_SIGNAL_FIELDS)

    server = OpcUaServerSimulator(endpoint=_opcua_endpoint())
    await server.start()
    try:
        payload = opcua_payload(device_id, endpoint=server.endpoint)
        payload["poll_interval_ms"] = POLL_MS
        payload["opc_ua"]["nodes"] = {
            signal: {"node_id": node_id} for signal, node_id in server.node_ids.items()
        }
        version = await _publish(sessions, device_id, payload)

        resolved = await _resolve(sessions)
        assert [(item.device_id, item.source) for item in resolved] == [
            (device_id, ConfigurationSource.DATABASE)
        ]

        chain = _build_gateway(
            sessions=sessions,
            definitions=resolved,
            cache=FakeLatestCache(),
            counters=IngestionCounters(),
        )
        try:
            await chain.gateway.start()
            applied = await chain.applier.apply(resolved[0].definition, version=version)
            assert applied.applied is True, applied.error
            assert applied.runtime_state == "CONNECTED"

            rows = await _wait_for_telemetry(sessions, device_id)
            first = rows[0]
            _assert_close(first.temperature_c, OPCUA_ENSEMBLE["temperature"])
            _assert_close(first.bearing_temperature_c, OPCUA_ENSEMBLE["bearing_temperature"])
            _assert_close(first.vibration_mm_s, OPCUA_ENSEMBLE["vibration"])
            _assert_close(first.current_a, OPCUA_ENSEMBLE["current"])
            _assert_close(first.voltage_v, OPCUA_ENSEMBLE["voltage"])
            assert first.rpm == OPCUA_ENSEMBLE["rpm"]
            _assert_close(first.load_pct, OPCUA_ENSEMBLE["load"])
            _assert_close(first.power_kw, OPCUA_ENSEMBLE["power"])
        finally:
            await chain.gateway.stop()
    finally:
        await server.stop()


# ---------------------------------------------------------------------------
# Failure isolation and controlled reload
# ---------------------------------------------------------------------------


async def test_a_bad_version_cannot_take_a_healthy_runtime_down(
    sessions: async_sessionmaker[AsyncSession],
    modbus_server: ModbusTcpServerSimulator,
) -> None:
    """Publishing a version that cannot connect leaves the running runtime polling."""

    device_id = "MOTOR-001"
    await _seed_device(sessions, device_id)
    await _publish(sessions, device_id, _modbus_config(device_id, modbus_server.port))

    resolved = await _resolve(sessions)
    chain = _build_gateway(
        sessions=sessions,
        definitions=resolved,
        cache=FakeLatestCache(),
        counters=IngestionCounters(),
    )
    try:
        await chain.gateway.start()
        assert (await chain.applier.apply(resolved[0].definition, version=1)).applied is True
        await _wait_for_telemetry(sessions, device_id, minimum=2)
        before = await _count_telemetry(sessions, device_id)

        # Version 2 points at a closed port: the apply must fail without touching v1.
        await _publish(sessions, device_id, _modbus_config(device_id, _free_port()))

        async with sessions() as session:
            service = ConfigurationService(session, chain.applier)
            published = await service.get_configuration(device_id, 2)
            status = await service.apply_current(device_id, "integration")

        assert published.status == "PUBLISHED"
        assert status["desired_version"] == 2
        assert status["applied_version"] == 1
        assert status["apply_status"] == ApplyStatus.FAILED.value
        assert status["in_sync"] is False
        assert status["last_apply_error"]
        assert chain.gateway.applied_version(device_id) == 1
        assert chain.gateway.status(device_id).state.value == "CONNECTED"

        # The surviving v1 runtime is not merely reported healthy, it keeps ingesting.
        await _wait_for_telemetry(sessions, device_id, minimum=before + 2)
        assert await _count_telemetry(sessions, device_id) > before
    finally:
        await chain.gateway.stop()


async def test_reloading_one_device_leaves_the_other_untouched(
    sessions: async_sessionmaker[AsyncSession],
    modbus_server: ModbusTcpServerSimulator,
) -> None:
    """A controlled reload rebuilds exactly one runtime."""

    first = "MOTOR-001"
    second = "MOTOR-002"
    await _seed_device(sessions, first)
    await _seed_device(sessions, second)
    for device_id in (first, second):
        await _publish(sessions, device_id, _modbus_config(device_id, modbus_server.port))

    resolved = await _resolve(sessions)
    assert {item.device_id for item in resolved} == {first, second}
    chain = _build_gateway(
        sessions=sessions,
        definitions=resolved,
        cache=FakeLatestCache(),
        counters=IngestionCounters(),
    )
    try:
        await chain.gateway.start()
        for item in resolved:
            assert (await chain.applier.apply(item.definition, version=1)).applied is True

        await _wait_for_telemetry(sessions, second, minimum=1)
        second_before = await _count_telemetry(sessions, second)
        first_before = await _count_telemetry(sessions, first)

        # Republish only the first device, now pointing at a closed port.
        async with sessions() as session:
            service = ConfigurationService(session, UnavailableApplier())
            draft = await service.create_draft(
                first, _modbus_config(first, _free_port()), "integration"
            )
            await service.publish(first, draft.version, "integration")
            assert draft.version == 2

        async with sessions() as session:
            service = ConfigurationService(session, chain.applier)
            status_first = await service.apply_current(first, "integration")

        assert status_first["desired_version"] == 2
        assert status_first["applied_version"] == 1
        assert status_first["apply_status"] == ApplyStatus.FAILED.value

        # Neither device was disturbed by the failed reload of the other.
        assert chain.gateway.applied_version(first) == 1
        assert chain.gateway.applied_version(second) == 1
        assert chain.gateway.status(second).state.value == "CONNECTED"
        await _wait_for_telemetry(sessions, second, minimum=second_before + 2)
        await _wait_for_telemetry(sessions, first, minimum=first_before + 2)
    finally:
        await chain.gateway.stop()


# ---------------------------------------------------------------------------
# Restart recovery
# ---------------------------------------------------------------------------


async def test_restart_rebuilds_the_runtime_from_the_database(
    sessions: async_sessionmaker[AsyncSession],
    modbus_server: ModbusTcpServerSimulator,
) -> None:
    """A restart is answered from published configuration, not from a file.

    The YAML source is pointed at a path that does not exist. If a restart depended on
    a file, the inventory would come back empty. It comes back with v2 and the runtime
    publishes v2's state labels, which is the property under test.
    """

    device_id = "MOTOR-001"
    await _seed_device(sessions, device_id)
    await _publish(sessions, device_id, _modbus_config(device_id, modbus_server.port))
    await _publish(
        sessions,
        device_id,
        _modbus_config(
            device_id,
            modbus_server.port,
            state={"operating_state": "RUNNING", "fault_state": "DEGRADED"},
        ),
    )

    # A cold process: nothing in memory, and no bootstrap file on disk.
    resolved = await _resolve(sessions)
    assert len(resolved) == 1
    assert resolved[0].version == 2
    assert resolved[0].source is ConfigurationSource.DATABASE
    assert resolved[0].definition.state.fault_state == "DEGRADED"
    assert not NO_YAML.exists()

    chain = _build_gateway(
        sessions=sessions,
        definitions=resolved,
        cache=FakeLatestCache(),
        counters=IngestionCounters(),
    )
    try:
        await chain.gateway.start()
        confirmed = await chain.gateway.confirm_ready(
            device_id, version=2, timeout_seconds=APPLY_TIMEOUT
        )
        assert confirmed.applied is True, confirmed.error
        assert chain.gateway.applied_version(device_id) == 2

        # v2's labels reach the database, proving the restored runtime runs v2.
        rows = await _wait_for_telemetry(sessions, device_id)
        assert {row.fault_state for row in rows} == {"DEGRADED"}
    finally:
        await chain.gateway.stop()
