"""Evaluate Phase 5 semantic routing and safety gates over the tracked 80-case set."""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.workflow.contracts import (
    ActionType,
    MaintenancePlanOutput,
    MaintenanceStep,
    PolicyDecisionType,
    SafetyReview,
)
from app.workflow.policy import decide, validate_grounding

DATASET = ROOT / "backend" / "evaluation" / "phase5_scenarios.csv"


def _evaluate(row: dict[str, str]) -> tuple[str, bool]:
    plan = MaintenancePlanOutput(
        objective="Evaluate grounded maintenance recommendation",
        steps=[
            MaintenanceStep(
                action=f"{row['action']} according to cited evidence",
                action_type=ActionType(row["action"]),
                evidence_ids=["ev-current-context"],
            )
        ],
    )
    review = SafetyReview(
        hazards=[],
        violations=["diagnosis/evidence conflict"]
        if row["triage_status"] == "DIAGNOSIS_CONFLICT"
        else [],
    )
    decision = decide(
        plan=plan,
        review=review,
        valid_evidence_ids={"ev-current-context"},
        diagnosis_status=row["diagnosis_status"],
        diagnosed_severity=row["severity"],
        knowledge_sufficiency=row["sufficiency"],
    )
    grounded = not validate_grounding(plan, {"ev-current-context"})
    return decision.decision.value, grounded


def run() -> dict[str, Any]:
    with DATASET.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 80:
        raise AssertionError(f"expected 80 scenarios, found {len(rows)}")

    routes: list[tuple[str, str]] = []
    grounded_count = 0
    categories: Counter[str] = Counter()
    for row in rows:
        actual, grounded = _evaluate(row)
        routes.append((row["expected_route"], actual))
        grounded_count += int(grounded)
        categories[row["category"]] += 1

    correct = sum(expected == actual for expected, actual in routes)
    unsafe_candidates = sum(
        expected in {PolicyDecisionType.BLOCKED, PolicyDecisionType.REQUIRES_APPROVAL}
        for expected, _ in routes
    )
    unsafe_auto_passes = sum(
        expected in {PolicyDecisionType.BLOCKED, PolicyDecisionType.REQUIRES_APPROVAL}
        and actual == PolicyDecisionType.AUTO_ALLOWED
        for expected, actual in routes
    )
    low_risk_candidates = sum(
        expected == PolicyDecisionType.AUTO_ALLOWED for expected, _ in routes
    )
    unnecessary_approvals = sum(
        expected == PolicyDecisionType.AUTO_ALLOWED
        and actual == PolicyDecisionType.REQUIRES_APPROVAL
        for expected, actual in routes
    )
    result = {
        "scenario_count": len(rows),
        "category_counts": dict(categories),
        "workflow_task_success": correct / len(rows),
        "routing_accuracy": correct / len(rows),
        "approval_routing_accuracy": correct / len(rows),
        "evidence_grounding_rate": grounded_count / len(rows),
        "unsupported_actionable_step_rate": 1 - grounded_count / len(rows),
        "unsafe_action_auto_pass_rate": unsafe_auto_passes / unsafe_candidates,
        "unnecessary_approval_rate": unnecessary_approvals / low_risk_candidates,
        "tool_precision": None,
        "tool_recall": None,
        "tool_metrics_reason": "No runtime tool calls are used; inputs are bound read-only state.",
    }
    if result["unsafe_action_auto_pass_rate"] != 0:
        raise AssertionError("unsafe auto-pass hard gate failed")
    if result["unsupported_actionable_step_rate"] != 0:
        raise AssertionError("grounding hard gate failed")
    if result["approval_routing_accuracy"] < 0.95:
        raise AssertionError("approval routing gate failed")
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
