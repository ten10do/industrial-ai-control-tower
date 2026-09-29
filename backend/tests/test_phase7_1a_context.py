"""Phase 7.1-A DecisionContextBuilder tests against a real PostgreSQL server.

The builder's correctness depends on SQL semantics that a fake session cannot
prove: the current incident is excluded by primary key, ordering is total and
stable across equal timestamps, limits actually bound the result, and the
telemetry window is read in the documented order. Those are database
behaviours, so these tests use the same opt-in PostgreSQL harness the incident
suite uses.

Invocation::

    export ALARM_TEST_DATABASE_URL="postgresql+asyncpg://postgres:<pw>@localhost:5432/phase71a_test"
    pytest tests/test_phase7_1a_context.py -q
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alarm, Approval, Diagnosis, Incident, MaintenancePlan, WorkOrder
from app.workflow.context import (
    ALARM_LIMIT,
    CONTEXT_VERSION,
    HISTORY_LIMIT,
    SIMULATOR_BASELINE,
    TELEMETRY_WINDOW,
    WORK_ORDER_LIMIT,
    DecisionContextBuilder,
)
from tests.incidents.conftest import create_device, telemetry_payload, utc


async def _incident(
    session: AsyncSession,
    device_id: str,
    *,
    title: str = "incident",
    created_at=None,
    status: str = "CLOSED",
    severity: str = "MAJOR",
) -> Incident:
    incident = Incident(
        device_id=device_id,
        title=title,
        description="",
        status=status,
        priority="HIGH",
        severity=severity,
        created_at=created_at or utc(2026, 9, 20, 10, 0, 0),
    )
    session.add(incident)
    await session.flush()
    return incident


async def _diagnosis(
    session: AsyncSession,
    device_id: str,
    incident_id: UUID,
    *,
    created_at=None,
    fault_type: str = "BEARING_WEAR",
) -> Diagnosis:
    row = Diagnosis(
        incident_id=incident_id,
        device_id=device_id,
        status="FAULT",
        fault_type=fault_type,
        confidence=0.9,
        severity="HIGH",
        evidence=[],
        model_version="diagnosis-v1.1",
        created_at=created_at or utc(2026, 9, 20, 10, 0, 0),
    )
    session.add(row)
    await session.flush()
    return row


async def _telemetry(session: AsyncSession, device_id: str, *, base, count: int, **kwargs) -> None:
    from app.repositories.telemetry import TelemetryRepository
    from app.schemas.telemetry import TelemetryIn

    repo = TelemetryRepository(session)
    for index in range(count):
        payload = telemetry_payload(
            device_id, timestamp=base + timedelta(seconds=index), **kwargs
        )
        await repo.insert_once(TelemetryIn.model_validate(payload))


@pytest.mark.asyncio
async def test_history_excludes_current_incident_and_is_bounded(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-CTX")
    current = await _incident(session, "MOTOR-CTX", title="current", status="OPEN")
    # Insert more prior incidents than the cap so the limit is actually exercised.
    for index in range(HISTORY_LIMIT + 5):
        await _incident(
            session,
            "MOTOR-CTX",
            title=f"prior-{index}",
            created_at=utc(2026, 9, 1, 10, 0, 0) + timedelta(hours=index),
        )
    diagnosis = await _diagnosis(session, "MOTOR-CTX", current.id)
    await session.commit()

    context = await DecisionContextBuilder(session).build(current, diagnosis)

    ids = [item.incident_id for item in context.history]
    assert current.id not in ids
    assert len(context.history) == HISTORY_LIMIT
    assert context.history_limit == HISTORY_LIMIT
    # Newest first, deterministic.
    created = [item.created_at for item in context.history]
    assert created == sorted(created, reverse=True)
    assert context.context_version == CONTEXT_VERSION


@pytest.mark.asyncio
async def test_history_query_is_deterministic_across_repeated_builds(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-DET")
    current = await _incident(session, "MOTOR-DET", title="current", status="OPEN")
    # Equal created_at values force the id tiebreaker to matter.
    for index in range(4):
        await _incident(session, "MOTOR-DET", title=f"tie-{index}", created_at=utc(2026, 9, 5))
    diagnosis = await _diagnosis(session, "MOTOR-DET", current.id)
    await session.commit()

    first = await DecisionContextBuilder(session).build(current, diagnosis)
    second = await DecisionContextBuilder(session).build(current, diagnosis)

    assert [str(i.incident_id) for i in first.history] == [
        str(i.incident_id) for i in second.history
    ]


@pytest.mark.asyncio
async def test_linked_alarms_are_bounded_and_ordered(session: AsyncSession) -> None:
    from app.incidents.models import IncidentAlarm

    await create_device(session, "MOTOR-ALM")
    current = await _incident(session, "MOTOR-ALM", title="current", status="OPEN")
    diagnosis = await _diagnosis(session, "MOTOR-ALM", current.id)
    for index in range(ALARM_LIMIT + 3):
        alarm = Alarm(
            device_id="MOTOR-ALM",
            rule_id=f"rule_{index}",
            severity="CRITICAL",
            status="ACTIVE",
            message="m",
            started_at=utc(2026, 9, 10, 10, 0, 0) + timedelta(minutes=index),
            occurrence_count=1 + index,
        )
        session.add(alarm)
        await session.flush()
        session.add(IncidentAlarm(incident_id=current.id, alarm_id=alarm.id))
    await session.commit()

    context = await DecisionContextBuilder(session).build(current, diagnosis)

    assert len(context.linked_alarms) == ALARM_LIMIT
    started = [item.started_at for item in context.linked_alarms]
    assert started == sorted(started, reverse=True)


@pytest.mark.asyncio
async def test_prior_diagnosis_excludes_current_incident(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-PD")
    current = await _incident(session, "MOTOR-PD", title="current", status="OPEN")
    older = await _incident(session, "MOTOR-PD", title="older", created_at=utc(2026, 9, 1))
    await _diagnosis(session, "MOTOR-PD", older.id, fault_type="OVERHEATING")
    current_dx = await _diagnosis(session, "MOTOR-PD", current.id, fault_type="BEARING_WEAR")
    await session.commit()

    context = await DecisionContextBuilder(session).build(current, current_dx)

    assert context.prior_fault_type == "OVERHEATING"
    assert context.prior_diagnosis_id is not None


@pytest.mark.asyncio
async def test_maintenance_history_is_bounded_and_carries_approval(
    session: AsyncSession,
) -> None:
    await create_device(session, "MOTOR-WO")
    incident = await _incident(session, "MOTOR-WO", title="i", status="OPEN")
    diagnosis = await _diagnosis(session, "MOTOR-WO", incident.id)
    plan = MaintenancePlan(
        diagnosis_id=diagnosis.id,
        version=1,
        objective="o",
        steps=[],
        status="READY",
        payload={},
    )
    session.add(plan)
    await session.flush()
    approval = Approval(
        maintenance_plan_id=plan.id,
        decision="APPROVED",
        plan_version=1,
        plan_hash="h",
        payload={},
    )
    session.add(approval)
    await session.flush()
    for index in range(WORK_ORDER_LIMIT + 2):
        session.add(
            WorkOrder(
                maintenance_plan_id=plan.id,
                approval_id=approval.id,
                device_id="MOTOR-WO",
                incident_id=incident.id,
                diagnosis_id=diagnosis.id,
                title=f"wo-{index}",
                priority="HIGH",
                plan={},
                evidence_refs=[],
                safety_requirements=[],
                status="DRAFT",
                payload={},
                created_at=utc(2026, 9, 15, 10, 0, 0) + timedelta(hours=index),
            )
        )
    await session.commit()

    context = await DecisionContextBuilder(session).build(incident, diagnosis)

    assert len(context.maintenance_history) == WORK_ORDER_LIMIT
    assert all(item.approval_status == "APPROVED" for item in context.maintenance_history)


@pytest.mark.asyncio
async def test_device_health_uses_fixed_window_and_reports_baseline_source(
    session: AsyncSession,
) -> None:
    await create_device(session, "MOTOR-HL")
    incident = await _incident(session, "MOTOR-HL", title="i", status="OPEN")
    diagnosis = await _diagnosis(session, "MOTOR-HL", incident.id)
    # More samples than the window, so the window is genuinely bounded.
    await _telemetry(
        session,
        "MOTOR-HL",
        base=utc(2026, 9, 20, 10, 0, 0),
        count=TELEMETRY_WINDOW + 5,
        current_a=12.0,
    )
    await session.commit()

    context = await DecisionContextBuilder(session).build(incident, diagnosis)
    health = context.device_health

    assert health is not None
    assert health.sample_count == TELEMETRY_WINDOW
    assert health.window_size == TELEMETRY_WINDOW
    assert health.sufficient is True
    # No configured baseline for this device, so the explicit fallback is used
    # and named.
    assert health.baseline_source == "simulator_fallback"
    # current_a=12.0 against a fallback baseline of 10.0 is a 0.2 ratio.
    assert health.deviation_ratios["current_a"] == pytest.approx(0.2, abs=1e-6)
    assert health.max_deviation_ratio >= 0.2


@pytest.mark.asyncio
async def test_device_health_prefers_configured_baseline(session: AsyncSession) -> None:
    device = await create_device(session, "MOTOR-CFG")
    device.device_metadata = {"baseline": {"current_a": 12.0}}
    incident = await _incident(session, "MOTOR-CFG", title="i", status="OPEN")
    diagnosis = await _diagnosis(session, "MOTOR-CFG", incident.id)
    await _telemetry(
        session,
        "MOTOR-CFG",
        base=utc(2026, 9, 20, 10, 0, 0),
        count=TELEMETRY_WINDOW,
        current_a=12.0,
    )
    await session.commit()

    context = await DecisionContextBuilder(session).build(incident, diagnosis)
    health = context.device_health

    assert health is not None
    assert health.baseline_source == "device_config"
    # current_a matches the configured baseline exactly, so no deviation.
    assert health.deviation_ratios["current_a"] == pytest.approx(0.0, abs=1e-6)


@pytest.mark.asyncio
async def test_device_health_is_insufficient_below_minimum_samples(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-SHORT")
    incident = await _incident(session, "MOTOR-SHORT", title="i", status="OPEN")
    diagnosis = await _diagnosis(session, "MOTOR-SHORT", incident.id)
    await _telemetry(
        session,
        "MOTOR-SHORT",
        base=utc(2026, 9, 20, 10, 0, 0),
        count=1,
    )
    await session.commit()

    context = await DecisionContextBuilder(session).build(incident, diagnosis)
    health = context.device_health

    assert health is not None
    assert health.sufficient is False
    assert health.band == "UNKNOWN"
    assert health.notes


@pytest.mark.asyncio
async def test_device_health_exact_result_is_reproducible(session: AsyncSession) -> None:
    await create_device(session, "MOTOR-REP")
    incident = await _incident(session, "MOTOR-REP", title="i", status="OPEN")
    diagnosis = await _diagnosis(session, "MOTOR-REP", incident.id)
    await _telemetry(
        session,
        "MOTOR-REP",
        base=utc(2026, 9, 20, 10, 0, 0),
        count=TELEMETRY_WINDOW,
        current_a=13.0,
        vibration_mm_s=2.4,
    )
    await session.commit()

    first = await DecisionContextBuilder(session).build(incident, diagnosis)
    second = await DecisionContextBuilder(session).build(incident, diagnosis)

    assert first.device_health is not None and second.device_health is not None
    assert first.device_health.model_dump_json() == second.device_health.model_dump_json()
    # The fallback baseline is the documented simulator constant, not a made-up value.
    assert SIMULATOR_BASELINE["vibration_mm_s"] == 1.8
