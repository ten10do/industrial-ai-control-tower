"""Verify Diagnosis v1.1 -> knowledge retrieval -> evidence -> REST."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

import asyncpg
import httpx

API = os.getenv("PHASE4_API_URL", "http://localhost:48000")
POSTGRES_DSN = os.getenv(
    "PHASE4_POSTGRES_DSN",
    "postgresql://postgres:change-me-in-dotenv@localhost:45432/industrial_ai_control_tower",
)
DEVICE_ID = "MOTOR-001"
EXPECTED_DOCUMENTS = {
    "BEARING_WEAR": {"skf-bearing-maintenance-handbook", "abb-low-voltage-motors-2004"},
    "OVERLOAD": {
        "abb-low-voltage-motors-2004",
        "doe-motor-load-efficiency",
        "doe-oversized-motor",
        "doe-nuisance-tripping-2012",
    },
    "MISALIGNMENT": {"doe-shaft-alignment-2012", "abb-low-voltage-motors-2004"},
}


async def run() -> dict[str, Any]:
    result: dict[str, Any] = {}
    connection = await asyncpg.connect(POSTGRES_DSN)
    try:
        audit_before = int(
            await connection.fetchval("SELECT count(*) FROM retrieval_runs")
        )
        async with httpx.AsyncClient(base_url=API, timeout=30.0) as client:
            ready = await client.get("/ready")
            ready.raise_for_status()
            assert ready.json()["dependencies"]["diagnosis"] == "loaded"
            assert ready.json()["dependencies"]["knowledge"] == "indexed"
            history = await client.get(
                f"/api/v1/devices/{DEVICE_ID}/diagnoses", params={"limit": 500}
            )
            history.raise_for_status()
            diagnoses = history.json()["items"]
            for fault_type, expected_documents in EXPECTED_DOCUMENTS.items():
                diagnosis = next(
                    item
                    for item in diagnoses
                    if item["fault_type"] == fault_type and item["status"] == "FAULT"
                )
                response = await client.post(
                    f"/api/v1/devices/{DEVICE_ID}/knowledge-context",
                    json={"diagnosis_id": diagnosis["id"], "top_k": 5},
                )
                response.raise_for_status()
                context = response.json()
                assert context["sufficiency"]["status"] in {"SUFFICIENT", "PARTIAL"}
                assert context["evidence"]
                assert any(
                    evidence["document_id"] in expected_documents
                    for evidence in context["evidence"]
                )
                assert all(
                    evidence["citation"]["source"] for evidence in context["evidence"]
                )
                result[fault_type] = {
                    "diagnosis_id": diagnosis["id"],
                    "status": context["sufficiency"]["status"],
                    "documents": [item["document_id"] for item in context["evidence"]],
                }
            unsupported = await client.post(
                "/api/v1/knowledge/search",
                json={
                    "knowledge_query": {
                        "device_type": "industrial_motor",
                        "fault_type": "QUANTUM_TELEPORT",
                        "severity": "CRITICAL",
                        "symptoms": ["MOTOR-999 quantum bearing teleport failure"],
                        "objective": "troubleshooting",
                    }
                },
            )
            unsupported.raise_for_status()
            unsupported_payload = unsupported.json()
            assert (
                unsupported_payload["sufficiency"]["status"] == "INSUFFICIENT_EVIDENCE"
            )
            result["unsupported"] = unsupported_payload["sufficiency"]
        audit_after = int(
            await connection.fetchval("SELECT count(*) FROM retrieval_runs")
        )
        assert audit_after == audit_before + 4
        result["retrieval_audit"] = {"before": audit_before, "after": audit_after}
        result["end_to_end"] = "PASS"
        return result
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    print(json.dumps(asyncio.run(run()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
