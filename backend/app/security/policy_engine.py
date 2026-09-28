"""The governance Policy Engine (Phase 6.13-C).

RBAC answers "does this identity's role hold this permission". The governance
layer answers one more question, asked *after* RBAC says yes: "does a rule
above RBAC refuse it right now". Policies can only refuse. A policy that
grants would be a second authorization system, and this phase adds none.

Evaluation is centralized here the way scope decisions are centralized in
:mod:`app.security.scope_policy`: no route consults ``governance_policies``
directly. The single enforcement point is :func:`ensure_policy_allows`, called
from ``require_permission`` after the RBAC check passes, so every governed
route in the platform inherits policy evaluation without a per-route edit.

Conditions are a JSONB object; all keys present must match (AND). Supported
keys, deliberately few:

* ``roles``        — list of role names; matches when the caller holds any.
* ``time_window``  — ``{"days": [1..7] (ISO, Monday=1), "start": "HH:MM",
  "end": "HH:MM"}`` evaluated in UTC; a window whose end is not after its
  start wraps midnight.
* ``always``       — ``true``; matches every request. This is the change-freeze
  rule: a DENY with no conditions refuses the permission for everyone,
  including ADMIN, because governance boundaries sit above RBAC.

An unknown condition key never matches (the policy is inert for that request)
and never raises: a malformed rule must not turn every governed route into a
500. Write-time validation in the API rejects unknown keys, so an inert policy
requires out-of-band database editing to exist; the evaluate endpoint surfaces
the reason either way. Phase 6.13-D removes the silence around it: an
uninterpretable rule increments ``governance_invalid_policy_total`` and emits a
structured warning carrying the policy name, and the compliance dashboard
counts it, so a policy that enforces nothing is visible instead of quiet.

Phase 6.13-D also closes the fail-open path. Evaluation requires a database
session; there is no ``session=None → allowed`` compatibility branch left. A
database failure or an unexpected evaluator error raises ``503
GOVERNANCE_UNAVAILABLE`` — governance semantics are unavailable, so the
request is refused, never waved through. Denials are audited as
``POLICY_DENIED`` with the acting identity before the 403 is raised, exactly
like ``PERMISSION_DENIED`` and ``SCOPE_DENIED``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.platform_observability.metrics import (
    governance_evaluation_error_total,
    governance_invalid_policy_total,
    governance_policy_denied_total,
)
from app.security.audit import (
    ACTION_POLICY_DENIED,
    POLICY_RESOURCE,
    STATUS_DENIED,
    record_security_event,
)
from app.security.governance_models import GovernancePolicy, PolicyEffect
from app.security.rbac import Principal

logger = logging.getLogger(__name__)

POLICY_DENIED = "POLICY_DENIED"
GOVERNANCE_UNAVAILABLE = "GOVERNANCE_UNAVAILABLE"

#: Condition keys the engine understands. Anything else leaves the policy
#: inert for the request; the API refuses to store such a rule in the first
#: place, so this set is also the write-time validation source.
SUPPORTED_CONDITION_KEYS: frozenset[str] = frozenset({"roles", "time_window", "always"})


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """The outcome of one policy evaluation."""

    allowed: bool
    policy_name: str | None = None
    reason: str | None = None


def _parse_clock(value: object) -> time | None:
    if not isinstance(value, str):
        return None
    parts = value.split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour=hour, minute=minute)


def _matches_time_window(window: object, now: datetime) -> bool:
    """Evaluate a ``time_window`` condition against ``now`` (UTC)."""

    if not isinstance(window, dict):
        return False
    start = _parse_clock(window.get("start"))
    end = _parse_clock(window.get("end"))
    days = window.get("days")
    if start is None or end is None or not isinstance(days, list):
        return False
    if not all(isinstance(day, int) and 1 <= day <= 7 for day in days):
        return False
    if now.isoweekday() not in days:
        return False
    current = now.time().replace(second=0, microsecond=0)
    if start < end:
        return start <= current < end
    if start > end:
        # Wraps midnight: late evening of an included day still counts.
        return current >= start or current < end
    return False


def _conditions_match(
    conditions: dict[str, Any], principal: Principal, now: datetime, policy_name: str = ""
) -> bool:
    """All supported keys present must match; unsupported keys never match.

    An unsupported key leaves the rule inert but not silent: the counter and
    the structured warning name the policy, and the compliance dashboard
    reports the invalid count, so a rule that enforces nothing is visible.
    """

    if not conditions:
        return False
    for key, value in conditions.items():
        if key == "always":
            if value is not True:
                governance_invalid_policy_total.inc()
                logger.warning(
                    "governance_policy_invalid_condition",
                    extra={"policy": policy_name, "condition": key},
                )
                return False
        elif key == "roles":
            if not isinstance(value, list) or not (set(principal.roles) & set(value)):
                return False
        elif key == "time_window":
            if not _matches_time_window(value, now):
                return False
        else:
            governance_invalid_policy_total.inc()
            logger.warning(
                "governance_policy_unsupported_condition",
                extra={"policy": policy_name, "condition": key},
            )
            return False
    return True


async def _enabled_deny_policies(session: AsyncSession, permission: str) -> list[GovernancePolicy]:
    """Load the enabled DENY policies for one permission.

    Any database failure is a governance-layer failure, not an authorization
    answer: it is counted, logged, and surfaced as ``503
    GOVERNANCE_UNAVAILABLE``. Converting it into an empty policy list would be
    the fail-open path this phase exists to remove.
    """

    try:
        return list(
            await session.scalars(
                select(GovernancePolicy)
                .where(
                    GovernancePolicy.enabled.is_(True),
                    GovernancePolicy.permission == permission,
                    GovernancePolicy.effect == PolicyEffect.DENY.value,
                )
                .order_by(GovernancePolicy.name)
            )
        )
    except Exception as exc:
        governance_evaluation_error_total.inc()
        logger.exception(
            "governance_evaluation_failed",
            extra={"permission": permission},
        )
        raise AppError(
            GOVERNANCE_UNAVAILABLE,
            "The governance policy backend is unavailable; the request is refused.",
            503,
        ) from exc


async def evaluate(
    session: AsyncSession,
    principal: Principal,
    permission: str,
    *,
    now: datetime | None = None,
) -> PolicyDecision:
    """Return whether any enabled policy refuses this permission right now.

    The session is a required dependency: a caller without a database session
    cannot reach this function, and a database failure inside it raises
    ``503 GOVERNANCE_UNAVAILABLE`` rather than an ``allowed`` answer. There is
    deliberately no branch that returns a decision without consulting the
    policy store.
    """

    moment = now if now is not None else datetime.now(UTC)
    policies = await _enabled_deny_policies(session, permission)
    try:
        for policy in policies:
            conditions = dict(policy.conditions or {})
            if _conditions_match(conditions, principal, moment, policy.name):
                return PolicyDecision(
                    allowed=False,
                    policy_name=policy.name,
                    reason=f"Refused by governance policy {policy.name!r}.",
                )
    except Exception as exc:
        # A crashing condition matcher must never be read as "no policy
        # refused it". Same contract as a database failure: refuse, count,
        # log.
        governance_evaluation_error_total.inc()
        logger.exception(
            "governance_evaluation_failed",
            extra={"permission": permission},
        )
        raise AppError(
            GOVERNANCE_UNAVAILABLE,
            "The governance policy evaluator failed; the request is refused.",
            503,
        ) from exc
    return PolicyDecision(allowed=True)


async def ensure_policy_allows(
    session: AsyncSession,
    principal: Principal,
    permission: str,
    *,
    method: str | None = None,
    path: str | None = None,
) -> PolicyDecision:
    """Refuse the request when a governance policy denies the permission.

    The denial is audited before the 403 is raised, with the acting identity,
    so a policy-enforced refusal leaves the same evidence a refused permission
    or an out-of-scope attempt does.
    """

    decision = await evaluate(session, principal, permission)
    if decision.allowed:
        return decision
    governance_policy_denied_total.inc()
    details: dict[str, str] = {"policy": decision.policy_name or "", "permission": permission}
    if method is not None:
        details["method"] = method
    if path is not None:
        details["path"] = path
    await record_security_event(
        session,
        action=ACTION_POLICY_DENIED,
        resource=POLICY_RESOURCE,
        resource_id=permission,
        status=STATUS_DENIED,
        details=details,
        actor=principal.username,
        actor_user_id=principal.user_id,
    )
    raise AppError(
        POLICY_DENIED,
        decision.reason or "Refused by a governance policy.",
        403,
        {"policy": decision.policy_name},
    )


__all__ = [
    "GOVERNANCE_UNAVAILABLE",
    "POLICY_DENIED",
    "POLICY_RESOURCE",
    "SUPPORTED_CONDITION_KEYS",
    "PolicyDecision",
    "ensure_policy_allows",
    "evaluate",
]
