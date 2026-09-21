"""Versioned deterministic plan-grounding and safety policy."""

from app.workflow.contracts import (
    ActionType,
    MaintenancePlanOutput,
    PolicyDecision,
    PolicyDecisionType,
    SafetyReview,
)

POLICY_VERSION = "safety-policy-v1"
APPROVAL_ACTIONS = {
    ActionType.STOP,
    ActionType.ISOLATE,
    ActionType.LOCKOUT_TAGOUT,
    ActionType.DISASSEMBLE,
    ActionType.REPLACE,
    ActionType.RESTART,
}


def validate_grounding(plan: MaintenancePlanOutput, valid_evidence_ids: set[str]) -> list[str]:
    violations: list[str] = []
    for index, step in enumerate(plan.steps, start=1):
        if not step.evidence_ids or not set(step.evidence_ids).issubset(valid_evidence_ids):
            violations.append(f"UNSUPPORTED_PLAN_STEP:{index}")
    return violations


def decide(
    *,
    plan: MaintenancePlanOutput,
    review: SafetyReview,
    valid_evidence_ids: set[str],
    diagnosis_status: str = "FAULT",
    diagnosed_severity: str | None = None,
    knowledge_sufficiency: str = "SUFFICIENT",
) -> PolicyDecision:
    reasons = validate_grounding(plan, valid_evidence_ids)
    if diagnosis_status != "FAULT":
        reasons.append("NEEDS_MORE_DIAGNOSTIC_EVIDENCE")
    if knowledge_sufficiency == "INSUFFICIENT_EVIDENCE":
        reasons.append("INSUFFICIENT_EVIDENCE")
    reasons.extend(f"SAFETY_VIOLATION:{item}" for item in review.violations)
    if reasons:
        return PolicyDecision(
            decision=PolicyDecisionType.BLOCKED,
            policy_version=POLICY_VERSION,
            reasons=list(dict.fromkeys(reasons)),
        )
    actions = {step.action_type for step in plan.steps}
    severity = (diagnosed_severity or "MEDIUM").upper()
    approval_reasons: list[str] = []
    if severity in {"HIGH", "CRITICAL"}:
        approval_reasons.append(f"{severity}_SEVERITY")
    approval_reasons.extend(sorted(str(action) for action in actions & APPROVAL_ACTIONS))
    if approval_reasons:
        return PolicyDecision(
            decision=PolicyDecisionType.REQUIRES_APPROVAL,
            policy_version=POLICY_VERSION,
            reasons=list(dict.fromkeys(approval_reasons)),
        )
    return PolicyDecision(
        decision=PolicyDecisionType.AUTO_ALLOWED,
        policy_version=POLICY_VERSION,
        reasons=["LOW_RISK_GROUNDED_PLAN"],
    )
