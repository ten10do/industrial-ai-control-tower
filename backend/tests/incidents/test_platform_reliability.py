"""Phase 6.10 data-reliability tests (DB-backed).

Covers the ingestion guarantees the platform makes under adverse input:

- duplicate telemetry never duplicates an alarm;
- out-of-order telemetry never displaces the newest reading (latest wins);
- a repeated event (double acknowledge) is rejected and audited once;
- the three operator-critical actions always leave audit rows:
  alarm acknowledge, incident transition, workflow start.
"""

import json
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents.errors import AlarmLifecycleError
from app.incidents.incident_service import IncidentLifecycleService
from app.incidents.service import AlarmLifecycleService
from app.models import Alarm, AuditEvent, Diagnosis, Incident, Telemetry, WorkflowRun
from app.services.telemetry import IngestionCounters, TelemetryService
from app.websocket.manager import WebSocketManager
from tests.incidents.conftest import create_device, seed_rule, telemetry_payload, utc


class FakeRedis:
    """Minimal stand-in exposing the two calls the latest cache makes."""

    def __init__(self) -> None:
        self.store: dict[bytes, bytes] = {}

    async def eval(self, script: str, keys: int, key: str, epoch: float, payload: str) -> int:
        existing = self.store.get(key.encode() + b":epoch")
        if existing is not None and float(existing) >= float(epoch):
            return 0
        self.store[key.encode() + b":epoch"] = str(epoch).encode()
        self.store[key.encode() + b":payload"] = payload.encode()
        return 1

    async def hget(self, key: str, field: str) -> bytes | None:
        return self.store.get(key.encode() + b":" + field.encode())


async def make_telemetry_service(
    session: AsyncSession,
) -> tuple[TelemetryService, IngestionCounters]:
    counters = IngestionCounters()
    service = TelemetryService(
        session=session,
        redis=FakeRedis(),  # type: ignore[arg-type]
        websocket_manager=WebSocketManager(),
        counters=counters,
        diagnosis=None,
    )
    return service, counters


def wire(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode()


# --------------------------------------------------------------------------- #
# Duplicate telemetry
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_duplicate_telemetry_creates_no_duplicate_alarm_or_rows(
    session: AsyncSession,
) -> None:
    await create_device(session, "MOTOR-001")
    await seed_rule(session, "temperature_high", signal_name="temperature", threshold=50.0)
    payload = telemetry_payload(temperature_c=91.5)
    service, counters = await make_telemetry_service(session)

    first = await service.ingest_payload("industrial/devices/MOTOR-001/telemetry", wire(payload))
    second = await service.ingest_payload("industrial/devices/MOTOR-001/telemetry", wire(payload))

    assert first.status == "PERSISTED"
    assert second.status == "DUPLICATE"
    assert counters.duplicates == 1
    telemetry_rows = int(await session.scalar(select(func.count()).select_from(Telemetry)) or 0)
    alarm_rows = int(await session.scalar(select(func.count()).select_from(Alarm)) or 0)
    incident_rows = int(await session.scalar(select(func.count()).select_from(Incident)) or 0)
    workflow_rows = int(await session.scalar(select(func.count()).select_from(WorkflowRun)) or 0)
    assert telemetry_rows == 1
    assert alarm_rows == 1  # exactly one alarm from the first accepted payload
    assert incident_rows == 0
    assert workflow_rows == 0


# --------------------------------------------------------------------------- #
# Out-of-order telemetry: latest timestamp wins
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_out_of_order_telemetry_keeps_latest_in_cache(
    session: AsyncSession,
) -> None:
    await create_device(session, "MOTOR-001")
    await seed_rule(session, "temperature_high", signal_name="temperature", threshold=50.0)
    newer = telemetry_payload(timestamp=utc(2026, 9, 23, 10, 5, 0), temperature_c=61.0)
    older = telemetry_payload(timestamp=utc(2026, 9, 23, 10, 1, 0), temperature_c=62.0)
    service, _ = await make_telemetry_service(session)

    first = await service.ingest_payload("industrial/devices/MOTOR-001/telemetry", wire(newer))
    second = await service.ingest_payload("industrial/devices/MOTOR-001/telemetry", wire(older))

    assert first.status == "PERSISTED"
    assert second.status == "PERSISTED"  # both readings are persisted
    latest = await service.cache.get("MOTOR-001")
    assert latest is not None
    assert latest.timestamp == utc(2026, 9, 23, 10, 5, 0)  # newest wins, not last-written


@pytest.mark.asyncio
async def test_repeated_event_double_acknowledge_audited_once(
    session: AsyncSession,
) -> None:
    await create_device(session, "MOTOR-001")
    await seed_rule(session, "temperature_high", signal_name="temperature", threshold=50.0)
    service, _ = await make_telemetry_service(session)
    await service.ingest_payload(
        "industrial/devices/MOTOR-001/telemetry", wire(telemetry_payload(temperature_c=91.5))
    )
    alarm = await session.scalar(select(Alarm).limit(1))
    assert alarm is not None

    lifecycle = AlarmLifecycleService(session)
    await lifecycle.acknowledge_alarm(alarm.id, actor="operator-a")
    with pytest.raises(AlarmLifecycleError):
        await lifecycle.acknowledge_alarm(alarm.id, actor="operator-b")

    audits = list(
        (
            await session.execute(
                select(AuditEvent).where(AuditEvent.action == "ALARM_ACKNOWLEDGED")
            )
        ).scalars()
    )
    assert len(audits) == 1
    assert audits[0].actor == "operator-a"


# --------------------------------------------------------------------------- #
# Audit coverage of operator-critical actions
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_alarm_acknowledge_produces_audit(
    session: AsyncSession,
) -> None:
    await create_device(session, "MOTOR-001")
    await seed_rule(session, "temperature_high", signal_name="temperature", threshold=50.0)
    service, _ = await make_telemetry_service(session)
    await service.ingest_payload(
        "industrial/devices/MOTOR-001/telemetry", wire(telemetry_payload(temperature_c=91.5))
    )
    alarm = await session.scalar(select(Alarm).limit(1))
    assert alarm is not None

    await AlarmLifecycleService(session).acknowledge_alarm(alarm.id, actor="operator-a")

    row = (
        (await session.execute(select(AuditEvent).where(AuditEvent.action == "ALARM_ACKNOWLEDGED")))
        .scalars()
        .first()
    )
    assert row is not None
    assert row.actor == "operator-a"
    assert row.details["alarm_id"] == str(alarm.id)


@pytest.mark.asyncio
async def test_incident_transition_produces_audit(
    session: AsyncSession,
) -> None:
    await create_device(session, "MOTOR-001")
    incident = Incident(
        id=uuid4(),
        device_id="MOTOR-001",
        title="Bearing alarm cluster",
        description="Correlated from 3 alarms",
        status="OPEN",
        severity="MAJOR",
        priority="HIGH",
    )
    session.add(incident)
    await session.flush()

    await IncidentLifecycleService(session).acknowledge_incident(incident.id, actor="operator-a")

    row = (
        (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "INCIDENT_ACKNOWLEDGED",
                    AuditEvent.resource == str(incident.id),
                )
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    assert row.actor == "operator-a"


@pytest.mark.asyncio
async def test_workflow_start_produces_audit(
    session: AsyncSession,
    sessions: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workflow start writes its audit row before the graph runs — even if the
    graph itself fails. This is what makes the human-decision entry point
    auditable independent of agent success."""

    from uuid import UUID

    from app.workflow.service import WorkflowService

    await create_device(session, "MOTOR-001")
    incident = Incident(
        id=uuid4(),
        device_id="MOTOR-001",
        title="Bearing alarm cluster",
        description="Correlated from 3 alarms",
        status="OPEN",
        severity="MAJOR",
        priority="HIGH",
    )
    session.add(incident)
    await session.flush()
    diagnosis_id = uuid4()
    session.add(
        Diagnosis(
            id=diagnosis_id,
            device_id="MOTOR-001",
            incident_id=incident.id,
            status="FAULT",
            fault_type="BEARING_WEAR",
            confidence=0.91,
            severity="MAJOR",
            evidence=[],
            model_version="diagnosis-v1.1",
        )
    )
    await session.commit()

    class FakeSufficiency:
        status = "SUFFICIENT"

        def model_dump(self, mode: str = "python", **kwargs: Any) -> dict[str, Any]:
            return {"status": self.status}

    class FakeRetrieval:
        sufficiency = FakeSufficiency()
        evidence: list[Any] = []
        corpus_version = "corpus-test"
        embedding_version = "embedding-test"
        latency_ms = 1.0

    class FakeKnowledgeIndex:
        def search(self, *args: Any, **kwargs: Any) -> FakeRetrieval:
            return FakeRetrieval()

    class FakeGraph:
        async def ainvoke(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("graph exploded")

    class FakeProvider:
        provider = "test"
        model = "test-model"

    service = WorkflowService(
        sessions=sessions,
        knowledge_index=FakeKnowledgeIndex(),  # type: ignore[arg-type]
        provider=FakeProvider(),  # type: ignore[arg-type]
        checkpointer=None,  # type: ignore[arg-type]
        max_attempts=1,
        backoff_seconds=0.0,
        timeout_seconds=1.0,
    )
    monkeypatch.setattr(service, "_graph", lambda workflow_id, trace_id: FakeGraph())

    from app.core.errors import AppError

    with pytest.raises(AppError):
        await service.start(incident.id, diagnosis_id, trace_id="trace-reliability-test")

    row = (
        (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "WORKFLOW_STARTED",
                    AuditEvent.resource == str(incident.id),
                )
            )
        )
        .scalars()
        .first()
    )
    assert row is not None
    assert row.actor == "workflow-engine"
    run = await session.get(WorkflowRun, UUID(row.details["workflow_run_id"]))
    assert run is not None
    assert run.status == "FAILED"
