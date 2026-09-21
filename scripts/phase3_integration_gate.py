"""Real Phase 3 Simulator -> MQTT -> diagnosis integration gate."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Self

import asyncpg
import httpx
import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "simulator"))

from simulator.faults import FaultConfig, FaultManager
from simulator.models import IndustrialMotor, Telemetry

API = os.getenv("PHASE3_API_URL", "http://localhost:28000")
MQTT_HOST = os.getenv("PHASE3_MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("PHASE3_MQTT_PORT", "21883"))
POSTGRES_DSN = os.getenv(
    "PHASE3_POSTGRES_DSN",
    "postgresql://postgres:change-me-in-dotenv@localhost:25432/industrial_ai_control_tower",
)
DEVICE_ID = "MOTOR-001"


def generate_scenario(
    fault_type: str | None,
    *,
    seed: int,
    start_time: datetime,
    ticks: int,
    severity: float = 0.9,
    duration: int = 55,
) -> list[Telemetry]:
    """Generate an independent, label-blind live scenario with Phase 1 simulator code."""
    motor = IndustrialMotor(device_id=DEVICE_ID, seed=seed, initial_load_pct=55.0)
    manager: FaultManager | None = None
    if fault_type is not None:
        manager = FaultManager(motor.rng)
        manager.add_fault(
            FaultConfig(
                fault_type=fault_type,
                start_tick=25,
                duration=duration,
                severity=severity,
                ramp_up_ticks=10,
                recovery_ticks=25,
            )
        )

    rows: list[Telemetry] = []
    for tick in range(ticks):
        effects: dict[str, float | int] = {}
        if manager is not None:
            effects = manager.effects_for_tick(tick)
            motor.set_fault_state(manager.current_state_label())
        rows.append(motor.step(effects, timestamp=start_time + timedelta(seconds=tick)))
    return rows


class Publisher:
    def __init__(self) -> None:
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def __enter__(self) -> Self:
        self.client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
        self.client.loop_start()
        return self

    def __exit__(self, *_: object) -> None:
        self.client.disconnect()
        self.client.loop_stop()

    def publish(self, rows: list[Telemetry]) -> None:
        topic = f"industrial/devices/{DEVICE_ID}/telemetry"
        for row in rows:
            result = self.client.publish(topic, row.model_dump_json_mqtt(), qos=1)
            result.wait_for_publish(timeout=10)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT publish failed with rc={result.rc}")


async def wait_for_latest(client: httpx.AsyncClient, timestamp: datetime) -> None:
    expected = timestamp.isoformat().replace("+00:00", "Z")
    for _ in range(300):
        response = await client.get(f"/api/v1/devices/{DEVICE_ID}/telemetry/latest")
        if response.status_code == 200 and response.json()["timestamp"] == expected:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"telemetry did not reach {expected}")


async def diagnoses(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get(
        f"/api/v1/devices/{DEVICE_ID}/diagnoses", params={"limit": 500}
    )
    response.raise_for_status()
    return list(response.json()["items"])


def in_interval(
    rows: list[dict[str, Any]], start: datetime, end: datetime
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if start
        <= datetime.fromisoformat(row["window_end"].replace("Z", "+00:00"))
        <= end
    ]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "statuses": dict(Counter(row["status"] for row in rows)),
        "fault_types": dict(Counter(row["fault_type"] or "NONE" for row in rows)),
        "max_confidence": max((row["confidence"] or 0.0 for row in rows), default=0.0),
        "max_anomaly_score": max(
            (row["anomaly_score"] or 0.0 for row in rows), default=0.0
        ),
    }


async def run_full() -> dict[str, Any]:
    results: dict[str, Any] = {}
    async with httpx.AsyncClient(base_url=API, timeout=20) as client:
        ready = await client.get("/ready")
        ready.raise_for_status()
        assert ready.json()["dependencies"]["diagnosis"] == "loaded"
        results["readiness"] = ready.json()

        created = await client.post(
            "/api/v1/devices",
            json={
                "device_id": DEVICE_ID,
                "device_type": "IndustrialMotor",
                "name": "Phase 3 integration motor",
            },
        )
        assert created.status_code in {201, 409}, created.text

        cursor = datetime.now(UTC).replace(microsecond=0)
        scenarios: list[tuple[str, str | None, int, int, float, int]] = [
            ("NORMAL", None, 424_200, 50, 0.0, 0),
            ("BEARING_WEAR", "BEARING_WEAR", 424_201, 150, 0.9, 55),
            ("OVERLOAD", "OVERLOAD", 424_202, 120, 0.65, 18),
            ("MISALIGNMENT", "MISALIGNMENT", 424_203, 150, 0.9, 55),
        ]
        intervals: dict[str, tuple[datetime, datetime]] = {}
        with Publisher() as publisher:
            for name, fault_type, seed, ticks, severity, duration in scenarios:
                rows = generate_scenario(
                    fault_type,
                    seed=seed,
                    start_time=cursor,
                    ticks=ticks,
                    severity=severity,
                    duration=duration,
                )
                publisher.publish(rows)
                await wait_for_latest(client, rows[-1].timestamp)
                intervals[name] = (rows[0].timestamp, rows[-1].timestamp)
                cursor = rows[-1].timestamp + timedelta(seconds=1)

        all_diagnoses = await diagnoses(client)
        assert all(row["status"] != "FAILED" for row in all_diagnoses)
        normal_rows = in_interval(all_diagnoses, *intervals["NORMAL"])
        assert normal_rows and normal_rows[0]["status"] == "NORMAL"
        results["NORMAL"] = summarize(normal_rows)

        for fault_type in ("BEARING_WEAR", "OVERLOAD", "MISALIGNMENT"):
            phase_rows = in_interval(all_diagnoses, *intervals[fault_type])
            matches = [
                row
                for row in phase_rows
                if row["status"] == "FAULT" and row["fault_type"] == fault_type
            ]
            assert matches, f"no live {fault_type} diagnosis: {summarize(phase_rows)}"
            best = max(matches, key=lambda row: row["confidence"] or 0.0)
            assert best["evidence"]
            assert best["model_version"] == "diagnosis-v1.1"
            assert best["feature_version"] == "features-v1"
            phase_end = intervals[fault_type][1]
            recovery_start = phase_end - timedelta(seconds=24)
            recovery_rows = in_interval(phase_rows, recovery_start, phase_end)
            assert any(row["status"] == "NORMAL" for row in recovery_rows), (
                f"{fault_type} did not recover toward NORMAL: {summarize(recovery_rows)}"
            )
            results[fault_type] = {
                **summarize(phase_rows),
                "best_match": {
                    "confidence": best["confidence"],
                    "severity": best["severity"],
                    "anomaly_score": best["anomaly_score"],
                    "evidence": best["evidence"],
                },
                "recovery": summarize(recovery_rows),
            }

        latest = await client.get(f"/api/v1/devices/{DEVICE_ID}/diagnoses/latest")
        latest.raise_for_status()
        results["latest_api"] = latest.json()

    connection = await asyncpg.connect(POSTGRES_DSN)
    try:
        diagnosis_count = int(
            await connection.fetchval(
                "SELECT count(*) FROM diagnoses WHERE device_id = $1", DEVICE_ID
            )
        )
        telemetry_count = int(
            await connection.fetchval(
                "SELECT count(*) FROM telemetry WHERE device_id = $1", DEVICE_ID
            )
        )
        assert diagnosis_count == len(all_diagnoses)
        assert telemetry_count == sum(item[3] for item in scenarios)
        results["postgres"] = {
            "diagnosis_count": diagnosis_count,
            "telemetry_count": telemetry_count,
        }
    finally:
        await connection.close()
    return results


async def run_warmup_probe() -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=API, timeout=20) as client:
        ready = await client.get("/ready")
        ready.raise_for_status()
        before = await diagnoses(client)
        latest = await client.get(f"/api/v1/devices/{DEVICE_ID}/telemetry/latest")
        latest.raise_for_status()
        last_timestamp = datetime.fromisoformat(
            latest.json()["timestamp"].replace("Z", "+00:00")
        )
        rows = generate_scenario(
            None,
            seed=525_200,
            start_time=last_timestamp + timedelta(seconds=1),
            ticks=5,
        )
        with Publisher() as publisher:
            publisher.publish(rows)
        await wait_for_latest(client, rows[-1].timestamp)
        for _ in range(100):
            after = await diagnoses(client)
            if len(after) > len(before):
                break
            await asyncio.sleep(0.1)
        assert len(after) == len(before) + 1
        return {
            "warmup": "PASS",
            "diagnoses_before": len(before),
            "diagnoses_after": len(after),
            "new_result": after[0],
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warmup-probe", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run_warmup_probe() if args.warmup_probe else run_full())
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
