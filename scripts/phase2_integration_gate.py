"""Real Phase 2 integration gate against an already running local Compose stack."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import paho.mqtt.publish as mqtt_publish
import websockets
from redis.asyncio import Redis

API = os.getenv("PHASE2_API_URL", "http://localhost:18000")
WS = os.getenv("PHASE2_WS_URL", "ws://localhost:18000")
MQTT_HOST = os.getenv("PHASE2_MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("PHASE2_MQTT_PORT", "11883"))
POSTGRES_DSN = os.getenv(
    "PHASE2_POSTGRES_DSN",
    "postgresql://postgres:change-me-in-dotenv@localhost:15432/industrial_ai_control_tower",
)
REDIS_URL = os.getenv("PHASE2_REDIS_URL", "redis://localhost:16379/0")
DEVICE_ID = "MOTOR-001"
ROOT = Path(__file__).resolve().parents[1]


async def wait_for_latest(client: httpx.AsyncClient, timestamp: str) -> dict[str, Any]:
    for _ in range(40):
        response = await client.get(f"/api/v1/devices/{DEVICE_ID}/telemetry/latest")
        if response.status_code == 200 and response.json()["timestamp"] == timestamp:
            return response.json()
        await asyncio.sleep(0.1)
    raise AssertionError(f"latest telemetry did not reach {timestamp}")


async def publish(payload: bytes) -> None:
    await asyncio.to_thread(
        mqtt_publish.single,
        f"industrial/devices/{DEVICE_ID}/telemetry",
        payload,
        qos=1,
        hostname=MQTT_HOST,
        port=MQTT_PORT,
    )


async def telemetry_count(connection: asyncpg.Connection[Any]) -> int:
    value = await connection.fetchval(
        "SELECT count(*) FROM telemetry WHERE device_id = $1", DEVICE_ID
    )
    return int(value)


async def main() -> None:
    results: dict[str, Any] = {}
    async with httpx.AsyncClient(base_url=API, timeout=10) as client:
        ready = await client.get("/ready")
        ready.raise_for_status()
        results["ready"] = ready.json()

        created = await client.post(
            "/api/v1/devices",
            json={
                "device_id": DEVICE_ID,
                "device_type": "IndustrialMotor",
                "name": "Phase 2 integration motor",
            },
        )
        assert created.status_code in {201, 409}, created.text
        listed = await client.get("/api/v1/devices")
        listed.raise_for_status()
        assert any(item["device_id"] == DEVICE_ID for item in listed.json())
        results["device_api"] = "PASS"

        async with websockets.connect(
            f"{WS}/ws/devices/{DEVICE_ID}/telemetry"
        ) as websocket:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "simulator",
                "--device-id",
                DEVICE_ID,
                "--mqtt-broker-host",
                MQTT_HOST,
                "--mqtt-broker-port",
                str(MQTT_PORT),
                "--sample-interval",
                "0.05",
                "--max-ticks",
                "5",
                cwd=ROOT / "simulator",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            live_raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
            assert process.returncode == 0, stderr.decode()
            live = json.loads(live_raw)
            assert live["device_id"] == DEVICE_ID
            results["simulator_messages_printed"] = len(stdout.decode().splitlines())
            results["websocket"] = "PASS"

        latest_response = await client.get(
            f"/api/v1/devices/{DEVICE_ID}/telemetry/latest"
        )
        latest_response.raise_for_status()
        simulator_latest = latest_response.json()
        base_time = datetime.fromisoformat(
            simulator_latest["timestamp"].replace("Z", "+00:00")
        )

        manual_time = (base_time + timedelta(seconds=10)).astimezone(UTC)
        manual = {
            key: simulator_latest[key]
            for key in (
                "schema_version",
                "device_id",
                "temperature_c",
                "bearing_temperature_c",
                "vibration_mm_s",
                "current_a",
                "voltage_v",
                "rpm",
                "load_pct",
                "power_kw",
                "operating_state",
                "fault_state",
            )
        }
        manual["timestamp"] = manual_time.isoformat().replace("+00:00", "Z")
        manual["temperature_c"] = 95.0
        await publish(json.dumps(manual).encode())
        await wait_for_latest(client, str(manual["timestamp"]))

        connection = await asyncpg.connect(POSTGRES_DSN)
        redis = Redis.from_url(REDIS_URL)
        try:
            count_after_new = await telemetry_count(connection)
            await publish(json.dumps(manual).encode())
            await asyncio.sleep(0.5)
            assert await telemetry_count(connection) == count_after_new
            results["duplicate_policy"] = "PASS"

            stale = dict(manual)
            stale["timestamp"] = (
                (base_time + timedelta(seconds=5))
                .astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z")
            )
            await publish(json.dumps(stale).encode())
            for _ in range(30):
                if await telemetry_count(connection) == count_after_new + 1:
                    break
                await asyncio.sleep(0.1)
            assert await telemetry_count(connection) == count_after_new + 1
            raw_cache = await redis.hget(f"device:{DEVICE_ID}:latest", "payload")
            assert raw_cache is not None
            cached = json.loads(raw_cache)
            assert cached["timestamp"] == manual["timestamp"]
            results["out_of_order_policy"] = "PASS"
            results["redis_latest"] = "PASS"

            audit_before = int(
                await connection.fetchval("SELECT count(*) FROM audit_events")
            )
            await publish(b"not-json")
            unsupported = dict(manual)
            unsupported["timestamp"] = datetime.now(UTC).isoformat()
            unsupported["schema_version"] = "2.0"
            await publish(json.dumps(unsupported).encode())
            for _ in range(30):
                audit_after = int(
                    await connection.fetchval("SELECT count(*) FROM audit_events")
                )
                if audit_after >= audit_before + 2:
                    break
                await asyncio.sleep(0.1)
            assert audit_after >= audit_before + 2
            results["invalid_payload_audit"] = "PASS"
        finally:
            await redis.aclose()
            await connection.close()

        history = await client.get(
            f"/api/v1/devices/{DEVICE_ID}/telemetry", params={"limit": 3}
        )
        history.raise_for_status()
        assert 1 <= len(history.json()["items"]) <= 3
        alarms = await client.get("/api/v1/alarms", params={"device_id": DEVICE_ID})
        alarms.raise_for_status()
        assert any(alarm["rule_id"] == "HIGH_TEMPERATURE" for alarm in alarms.json())
        results["rest_history_latest_alarm"] = "PASS"

    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
