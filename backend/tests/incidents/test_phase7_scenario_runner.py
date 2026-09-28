"""DB-backed proof that ScenarioRunner uses the canonical production path."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ml.runtime import ModelRuntime
from app.models import Incident, Telemetry
from app.scenarios.contracts import ScenarioDefinition
from app.scenarios.runner import ScenarioRunner
from app.services.diagnosis import OnlineDiagnosisCoordinator
from tests.incidents.conftest import seed_rule


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    async def eval(self, script: str, keys: int, key: str, epoch: float, payload: str) -> int:
        current = self.values.get(f"{key}:epoch")
        if current is not None and float(current) >= epoch:
            return 0
        self.values[f"{key}:epoch"] = str(epoch).encode()
        self.values[f"{key}:payload"] = payload.encode()
        return 1

    async def hget(self, key: str, field: str) -> bytes | None:
        return self.values.get(f"{key}:{field}")


def scenario() -> ScenarioDefinition:
    return ScenarioDefinition.model_validate(
        {
            "scenario_id": "db_backed_bearing",
            "description": "DB-backed bearing scenario",
            "kind": "PROGRESSIVE_FAULT",
            "device": {"device_id": "PH7-DB-001", "seed": 501},
            "fault": {"type": "BEARING_WEAR", "severity": 1.0},
            "execution": {
                "warmup_seconds": 20,
                "fault_duration_seconds": 30,
                "recovery_seconds": 5,
            },
            "expected": {
                "alarm": {"required": True, "max_instances": 2},
                "incident": {"required": True, "max_count": 1},
                "diagnosis": {"expected_fault": "BEARING_WEAR"},
                "evidence": {},
                "workflow": {},
                "safety": {},
                "workorder": {},
            },
        }
    )


@pytest.mark.asyncio
async def test_runner_persists_simulator_data_and_correlates_real_incident(
    session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await seed_rule(
        session,
        "HIGH_TEMPERATURE",
        signal_name="temperature",
        threshold=90.0,
        severity="CRITICAL",
    )
    await seed_rule(
        session,
        "HIGH_VIBRATION",
        signal_name="vibration",
        threshold=7.0,
        severity="MAJOR",
    )
    await session.commit()
    backend = Path(__file__).parents[2]
    runtime = ModelRuntime.load(
        backend / "artifacts" / "diagnosis-v1.1.joblib",
        backend / "artifacts" / "model_manifest-v1.1.json",
    )
    runner = ScenarioRunner(
        sessions=sessions,
        redis=FakeRedis(),  # type: ignore[arg-type]
        diagnosis=OnlineDiagnosisCoordinator(runtime, sessions),
        knowledge_index=None,
        workflow=None,
    )

    result = await runner.run(scenario())

    telemetry_count = int(await session.scalar(select(func.count()).select_from(Telemetry)) or 0)
    incident_count = int(await session.scalar(select(func.count()).select_from(Incident)) or 0)
    assert telemetry_count == 56
    assert incident_count == 1
    assert result.alarm.observed["count"] >= 1
    assert result.incident.observed["count"] == 1
    assert result.workflow.status == "BLOCKED"
