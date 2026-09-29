"""Versioned deterministic risk assessment.

This module is the only place in the workflow that turns situation facts into a
risk band, and it is deliberately arithmetic. There is no model call, no clock
read, no randomness, and no I/O. Every factor reads exactly one field of the
already-assembled :class:`~app.workflow.contracts.DecisionContext` (or of the
diagnosis snapshot) and contributes a bounded weighted amount, so the same input
produces byte-identical output and a reviewer can trace each contribution back
to its source.

The assessment is decision support, not authorization. It carries review
attention, including the "history of repeat failures on this device" signal that
the incident itself does not express. It never blocks, never approves, and never
auto-passes. :func:`app.workflow.policy.decide` remains the single authority
over that, and the graph keeps the two separate: risk is computed before the
agents run, policy is computed after.
"""

from __future__ import annotations

from app.workflow.contracts import (
    DecisionContext,
    DiagnosisSnapshot,
    RiskAssessment,
    RiskFactor,
    RiskLevel,
)

#: Bump whenever a weight, a threshold, or a factor definition changes. The value
#: is embedded in every emitted assessment, so a stored assessment is always
#: interpretable against the policy that produced it.
RISK_POLICY_VERSION = "risk-policy-v1"

#: Ordered banding thresholds. A score ``>=`` the threshold takes that band,
#: evaluated from highest to lowest. Fixed constants, never derived at runtime.
_BANDS: tuple[tuple[float, RiskLevel], ...] = (
    (0.75, RiskLevel.CRITICAL),
    (0.5, RiskLevel.HIGH),
    (0.25, RiskLevel.MEDIUM),
    (0.0, RiskLevel.LOW),
)

#: Severity vocabulary shared with the diagnosis and alarm models. An unknown
#: severity maps to the MEDIUM default rather than to zero: treating an
#: unrecognised label as harmless would be the one failure mode that silently
#: understates risk.
_SEVERITY_WEIGHT: dict[str, float] = {
    "CRITICAL": 1.0,
    "HIGH": 0.75,
    "MAJOR": 0.75,
    "MEDIUM": 0.5,
    "WARNING": 0.4,
    "LOW": 0.25,
    "MINOR": 0.2,
    "INFO": 0.1,
}
_SEVERITY_DEFAULT = 0.5

#: Factor weights. Sum of the base weights is 1.0; ``evidence`` and
#: ``history`` re-normalise when a signal is absent, so a sparse context never
#: inflates or deflates the score through missing data.
_WEIGHT_SEVERITY = 0.35
_WEIGHT_ALARMS = 0.20
_WEIGHT_DEVICE_HEALTH = 0.25
_WEIGHT_EVIDENCE = 0.10
_WEIGHT_HISTORY = 0.10

#: A bounded ceiling for the "history of repeat failures" signal. Ten or more
#: prior incidents on one device saturate the factor; the count never scales the
#: contribution past its weight.
_HISTORY_SATURATION = 10.0

#: Alarm-severity attention value for a linked alarm of each severity.
_ALARM_ATTENTION: dict[str, float] = {
    "CRITICAL": 1.0,
    "MAJOR": 0.85,
    "HIGH": 0.85,
    "WARNING": 0.5,
    "MEDIUM": 0.5,
    "MINOR": 0.25,
    "LOW": 0.25,
    "INFO": 0.1,
}
_ALARM_ATTENTION_DEFAULT = 0.5


def _band(score: float) -> RiskLevel:
    for threshold, level in _BANDS:
        if score >= threshold:
            return level
    return RiskLevel.LOW


def _severity_weight(severity: str | None) -> float:
    if severity is None:
        return _SEVERITY_DEFAULT
    return _SEVERITY_WEIGHT.get(severity.upper(), _SEVERITY_DEFAULT)


def assess_risk(
    *, context: DecisionContext | None, diagnosis: DiagnosisSnapshot
) -> RiskAssessment:
    """Return the deterministic risk assessment for one situation.

    ``context`` is optional so a pre-7.1 or context-degraded run still produces
    an assessment from the diagnosis alone. When context is absent, the
    context-derived weights re-normalise rather than counting as zero, so the
    score reflects only the signals actually available.
    """

    factors: list[RiskFactor] = []

    severity_score = _severity_weight(diagnosis.severity)
    factors.append(
        RiskFactor(
            name="diagnosis_severity",
            weight=_WEIGHT_SEVERITY,
            contribution=_WEIGHT_SEVERITY * severity_score,
            evidence_ref="diagnosis.severity",
        )
    )

    available = _WEIGHT_SEVERITY

    if context is not None:
        alarm_score = _alarm_attention(context)
        factors.append(
            RiskFactor(
                name="linked_alarm_activity",
                weight=_WEIGHT_ALARMS,
                contribution=_WEIGHT_ALARMS * alarm_score,
                evidence_ref="decision_context.linked_alarms",
            )
        )
        available += _WEIGHT_ALARMS

        health_score = _device_health_attention(context)
        factors.append(
            RiskFactor(
                name="device_health_deviation",
                weight=_WEIGHT_DEVICE_HEALTH,
                contribution=_WEIGHT_DEVICE_HEALTH * health_score,
                evidence_ref="decision_context.device_health",
            )
        )
        available += _WEIGHT_DEVICE_HEALTH

        evidence_score, evidence_present = _evidence_attention(diagnosis)
        if evidence_present:
            factors.append(
                RiskFactor(
                    name="sensor_evidence_present",
                    weight=_WEIGHT_EVIDENCE,
                    contribution=_WEIGHT_EVIDENCE * evidence_score,
                    evidence_ref="diagnosis.sensor_evidence",
                )
            )
            available += _WEIGHT_EVIDENCE

        history_score = _history_attention(context)
        factors.append(
            RiskFactor(
                name="device_incident_history",
                weight=_WEIGHT_HISTORY,
                contribution=_WEIGHT_HISTORY * history_score,
                evidence_ref="decision_context.history",
            )
        )
        available += _WEIGHT_HISTORY

    raw = sum(factor.contribution for factor in factors)
    score = 0.0 if available <= 0 else raw / available
    score = min(1.0, max(0.0, score))

    # Round to a fixed precision so the score and the factor contributions are
    # stable across platforms and never carry sub-precision noise into a hash.
    score = round(score, 6)
    factors = [
        factor.model_copy(update={"contribution": round(factor.contribution, 6)})
        for factor in factors
    ]

    level = _band(score)
    rationale = _rationale(level, score, diagnosis, context)
    return RiskAssessment(
        level=level,
        score=score,
        factors=factors,
        policy_version=RISK_POLICY_VERSION,
        rationale=rationale,
    )


def _alarm_attention(context: DecisionContext) -> float:
    alarms = context.linked_alarms
    if not alarms:
        return 0.0
    worst = max(_ALARM_ATTENTION.get(a.severity.upper(), _ALARM_ATTENTION_DEFAULT) for a in alarms)
    # Recency and repetition add a bounded increment on top of the worst alarm.
    recurrence = min(1.0, sum(a.occurrence_count for a in alarms) / 10.0)
    return min(1.0, worst * 0.85 + recurrence * 0.15)


def _device_health_attention(context: DecisionContext) -> float:
    health = context.device_health
    if health is None or not health.sufficient:
        return 0.0
    ratio = health.max_deviation_ratio
    band_min = {"NOMINAL": 0.0, "ELEVATED": 0.4, "DEGRADED": 0.65, "CRITICAL": 0.9, "UNKNOWN": 0.0}
    base = band_min.get(health.band, 0.0)
    # Scale within the band, so a steadily worsening deviation moves the score
    # before it crosses the next band boundary.
    scale = min(1.0, max(0.0, ratio / 2.0))
    return min(1.0, base + (1.0 - base) * scale * 0.5)


def _evidence_attention(diagnosis: DiagnosisSnapshot) -> tuple[float, bool]:
    confidence = diagnosis.confidence
    if confidence is None:
        return 0.0, False
    return min(1.0, max(0.0, confidence)), True


def _history_attention(context: DecisionContext) -> float:
    count = len(context.history)
    if count == 0:
        return 0.0
    return min(1.0, count / _HISTORY_SATURATION)


def _rationale(
    level: RiskLevel,
    score: float,
    diagnosis: DiagnosisSnapshot,
    context: DecisionContext | None,
) -> list[str]:
    lines = [f"RISK_LEVEL:{level.value}", f"RISK_SCORE:{score:.6f}"]
    severity = (diagnosis.severity or "UNKNOWN").upper()
    lines.append(f"DIAGNOSIS_SEVERITY:{severity}")
    if context is None:
        lines.append("DECISION_CONTEXT:ABSENT")
        return lines
    lines.append(f"LINKED_ALARMS:{len(context.linked_alarms)}")
    lines.append(f"HISTORICAL_INCIDENTS:{len(context.history)}")
    if context.device_health is None or not context.device_health.sufficient:
        lines.append("DEVICE_HEALTH:INSUFFICIENT")
    else:
        lines.append(
            f"DEVICE_HEALTH:{context.device_health.band}"
            f"@max_ratio={context.device_health.max_deviation_ratio:.4f}"
        )
    return lines


__all__ = ["RISK_POLICY_VERSION", "assess_risk"]
