"""Alarm rule management and alarm lifecycle services.

Two services live here because they share one bounded context but not one
responsibility.

``AlarmRuleService`` owns the declarative rule registry. It validates definitions,
persists them, and reports which rules apply to a device type.

``AlarmLifecycleService`` owns condition state. It evaluates rules against a
telemetry payload, maintains one open instance per device and rule, and performs
the two operator commands that move an instance along its lifecycle.

Neither service controls a device. Rule evaluation reads a payload and writes
alarm rows, and the operator commands are database state changes. There is no
path from either service to an actuator, a protocol write, or a model call.

Auditing policy is deliberate and worth stating once. ``audit_events`` records
state changes, not activity volume. A breach against an instance that is already
open increments that instance and writes no audit row, because writing one per
sample would reproduce the flood this phase exists to remove. The instance
carries the volume itself, through ``occurrence_count`` and
``last_triggered_at``. Creation, acknowledgement, and clearing are state changes
and each writes exactly one audit row.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import trace_id_context
from app.incidents.contracts import AlarmRuleCreate, AlarmRuleUpdate
from app.incidents.errors import (
    AlarmNotFoundError,
    AlarmRuleConflictError,
    AlarmRuleNotFoundError,
    AlarmRuleValidationError,
    AlarmStateError,
)
from app.incidents.models import AlarmRule
from app.incidents.rules import (
    RuleBreach,
    canonical_readings,
    evaluate_rules,
    validate_rule_definition,
)
from app.incidents.states import (
    AlarmStatus,
    describe_alarm_transitions,
    is_alarm_transition_allowed,
)
from app.infrastructure.database.base import utc_now
from app.models import Alarm
from app.platform_observability.metrics import alarm_cleared_total, alarm_created_total
from app.repositories.alarm import AlarmRepository
from app.repositories.alarm_rule import AlarmRuleRepository
from app.repositories.audit import AuditRepository

logger = logging.getLogger(__name__)

DEFAULT_ACTOR = "backend"


def _instant_from_payload(payload: Mapping[str, Any]) -> datetime:
    """Derive the breach instant from the payload when the caller omits one.

    The telemetry contract carries the sample's event time, so an alarm should
    anchor to that rather than to ingestion wall clock time. An absent or
    unparseable timestamp falls back to ``utc_now`` rather than raising, because
    the ingestion path already validated the payload and a wall clock anchor is
    better than rejecting a persisted measurement.
    """

    value = payload.get("timestamp")
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else utc_now()
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return utc_now()
        return parsed if parsed.tzinfo is not None else utc_now()
    return utc_now()


_RULE_VALIDATION_FIELDS = (
    "id",
    "name",
    "signal_name",
    "operator",
    "threshold",
    "severity",
    "priority",
    "device_type",
)


class AlarmRuleService:
    """Reads and writes the declarative alarm rule registry."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.rules = AlarmRuleRepository(session)
        self.audit = AuditRepository(session)

    async def list_rules(self, *, enabled_only: bool = False) -> list[AlarmRule]:
        return await self.rules.list_rules(enabled_only=enabled_only)

    async def get_rule(self, rule_id: str) -> AlarmRule:
        rule = await self.rules.get(rule_id)
        if rule is None:
            raise AlarmRuleNotFoundError(f"alarm rule {rule_id!r} was not found")
        return rule

    async def applicable_rules(self, device_type: str | None) -> list[AlarmRule]:
        return await self.rules.list_applicable(device_type)

    async def create_rule(
        self, payload: AlarmRuleCreate, *, actor: str = DEFAULT_ACTOR
    ) -> AlarmRule:
        values = payload.model_dump()
        issues = validate_rule_definition(
            rule_id=values["id"],
            name=values["name"],
            signal_name=values["signal_name"],
            operator=values["operator"],
            threshold=values["threshold"],
            severity=values["severity"],
            priority=values["priority"],
            device_type=values["device_type"],
        )
        if issues:
            raise AlarmRuleValidationError("alarm rule definition is not usable", issues)
        if await self.rules.get(payload.id) is not None:
            raise AlarmRuleConflictError(
                f"alarm rule {payload.id!r} already exists", {"rule_id": payload.id}
            )
        rule = await self.rules.create(values)
        self._audit(
            action="ALARM_RULE_CREATED",
            resource=rule.id,
            actor=actor,
            details={
                "signal_name": rule.signal_name,
                "operator": rule.operator,
                "threshold": rule.threshold,
                "severity": rule.severity,
                "priority": rule.priority,
                "enabled": rule.enabled,
                "device_type": rule.device_type,
            },
        )
        await self.session.commit()
        return rule

    async def update_rule(
        self,
        rule_id: str,
        payload: AlarmRuleUpdate,
        *,
        actor: str = DEFAULT_ACTOR,
    ) -> AlarmRule:
        rule = await self.get_rule(rule_id)
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise AlarmRuleValidationError(
                "a rule patch must set at least one field",
                [{"field": "<root>", "code": "NO_FIELDS", "message": "patch body was empty"}],
            )
        merged: dict[str, Any] = {
            field: (changes[field] if field in changes else getattr(rule, field))
            for field in _RULE_VALIDATION_FIELDS
        }
        issues = validate_rule_definition(
            rule_id=merged["id"],
            name=merged["name"],
            signal_name=merged["signal_name"],
            operator=merged["operator"],
            threshold=merged["threshold"],
            severity=merged["severity"],
            priority=merged["priority"],
            device_type=merged["device_type"],
        )
        if issues:
            raise AlarmRuleValidationError(
                f"alarm rule patch for {rule_id!r} is not usable", issues
            )
        rule = await self.rules.apply_update(rule, changes)
        self._audit(
            action="ALARM_RULE_UPDATED",
            resource=rule.id,
            actor=actor,
            details={"changed_fields": sorted(changes)},
        )
        await self.session.commit()
        return rule

    def _audit(self, *, action: str, resource: str, actor: str, details: dict[str, Any]) -> None:
        self.audit.add(
            trace_id=trace_id_context.get(),
            actor=actor,
            action=action,
            resource=resource,
            status="SUCCESS",
            details=details,
        )


class AlarmLifecycleService:
    """Owns alarm instance state and the two operator commands on it."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.alarms = AlarmRepository(session)
        self.rules = AlarmRuleRepository(session)
        self.audit = AuditRepository(session)

    async def record_breaches(
        self,
        *,
        device_id: str,
        device_type: str | None,
        telemetry_id: UUID | None,
        payload: Mapping[str, Any],
        triggered_at: datetime | None = None,
        actor: str = DEFAULT_ACTOR,
    ) -> list[Alarm]:
        """Evaluate the applicable rules and fold the results into alarm state.

        This method does not commit. The caller owns the transaction, because
        ingestion commits telemetry and alarm state together so a persisted
        measurement cannot end up without the alarm it triggered.
        """

        rules = await self.rules.list_applicable(device_type)
        if not rules:
            return []
        breaches = evaluate_rules(rules, canonical_readings(payload), device_type=device_type)
        if not breaches:
            return []
        instant = triggered_at or _instant_from_payload(payload)
        touched: list[Alarm] = []
        for breach in breaches:
            alarm, _created = await self.create_or_update_alarm(
                device_id=device_id,
                breach=breach,
                telemetry_id=telemetry_id,
                triggered_at=instant,
                actor=actor,
            )
            touched.append(alarm)
        return touched

    async def create_or_update_alarm(
        self,
        *,
        device_id: str,
        breach: RuleBreach,
        telemetry_id: UUID | None,
        triggered_at: datetime | None = None,
        actor: str = DEFAULT_ACTOR,
    ) -> tuple[Alarm, bool]:
        """Return the open instance for a device and rule, creating it if absent.

        The deduplication requirement is that a thousand consecutive breaches
        produce one instance, not a thousand rows. An existing open instance is
        therefore updated in place: its ``occurrence_count`` rises, its
        ``last_triggered_at`` advances, and its message and severity move to the
        latest reading. ``started_at`` and ``telemetry_id`` are never rewritten,
        so the row keeps pointing at the first breach that opened the condition.
        """

        instant = triggered_at or utc_now()
        existing = await self.alarms.find_open(device_id, breach.rule_id)
        if existing is not None:
            self._apply_breach(existing, breach, instant)
            await self.session.flush()
            return existing, False

        try:
            async with self.session.begin_nested():
                alarm = await self.alarms.create(
                    device_id=device_id,
                    telemetry_id=telemetry_id,
                    rule_id=breach.rule_id,
                    severity=breach.severity,
                    message=breach.message,
                    started_at=instant,
                )
        except IntegrityError:
            # Two ingestion workers raced between the lookup and the insert and
            # the partial unique index refused the second one. The condition is
            # open, so the correct outcome is the update branch, not an error.
            existing = await self.alarms.find_open(device_id, breach.rule_id)
            if existing is None:
                raise
            logger.info(
                "alarm_open_instance_race_resolved",
                extra={"device_id": device_id, "rule_id": breach.rule_id},
            )
            self._apply_breach(existing, breach, instant)
            await self.session.flush()
            return existing, False

        alarm_created_total.labels(rule_id=breach.rule_id, severity=breach.severity).inc()
        self._audit(
            action="ALARM_CREATED",
            resource=device_id,
            actor=actor,
            details={
                "rule_id": breach.rule_id,
                "severity": breach.severity,
                "priority": breach.priority,
                "alarm_id": str(alarm.id),
                "observed": breach.observed,
                "threshold": breach.threshold,
            },
        )
        return alarm, True

    async def acknowledge_alarm(
        self,
        alarm_id: UUID,
        *,
        actor: str = DEFAULT_ACTOR,
        note: str | None = None,
    ) -> Alarm:
        """Move an alarm from ACTIVE to ACKNOWLEDGED.

        Acknowledgement means an operator has seen the condition. It does not
        clear it and it does not stop further breaches from incrementing the
        instance.
        """

        alarm = await self._require_alarm(alarm_id)
        current = self._status_of(alarm)
        self._require_transition(alarm, current, AlarmStatus.ACKNOWLEDGED)
        alarm.status = AlarmStatus.ACKNOWLEDGED.value
        alarm.acknowledged_at = utc_now()
        alarm.acknowledged_by = actor
        await self.session.flush()
        self._audit(
            action="ALARM_ACKNOWLEDGED",
            resource=alarm.device_id,
            actor=actor,
            details={
                "alarm_id": str(alarm.id),
                "rule_id": alarm.rule_id,
                "note": note,
                "occurrence_count": alarm.occurrence_count,
            },
        )
        await self.session.commit()
        return alarm

    async def clear_alarm(
        self,
        alarm_id: UUID,
        *,
        actor: str = DEFAULT_ACTOR,
        reason: str,
    ) -> Alarm:
        """Move an alarm from ACTIVE or ACKNOWLEDGED to CLEARED.

        ``CLEARED`` is terminal for an instance. A recurrence opens a new row, so
        this operation never has to be undone and the history of which condition
        covered which period stays intact.
        """

        alarm = await self._require_alarm(alarm_id)
        current = self._status_of(alarm)
        self._require_transition(alarm, current, AlarmStatus.CLEARED)
        alarm.status = AlarmStatus.CLEARED.value
        alarm.cleared_at = utc_now()
        alarm.clear_reason = reason
        await self.session.flush()
        alarm_cleared_total.labels(rule_id=alarm.rule_id, severity=alarm.severity).inc()
        self._audit(
            action="ALARM_CLEARED",
            resource=alarm.device_id,
            actor=actor,
            details={
                "alarm_id": str(alarm.id),
                "rule_id": alarm.rule_id,
                "reason": reason,
                "previous_status": current.value,
                "occurrence_count": alarm.occurrence_count,
            },
        )
        await self.session.commit()
        return alarm

    @staticmethod
    def _apply_breach(alarm: Alarm, breach: RuleBreach, instant: datetime) -> None:
        """Fold one breach into an open instance.

        ``last_triggered_at`` only ever moves forward. Telemetry can arrive out of
        order, and letting a late sample pull the latest activity backwards would
        make an active condition look stale and drop it out of a correlation
        window it belongs in.
        """

        alarm.occurrence_count = (alarm.occurrence_count or 0) + 1
        if alarm.last_triggered_at is None or instant > alarm.last_triggered_at:
            alarm.last_triggered_at = instant
        alarm.message = breach.message
        alarm.severity = breach.severity

    async def _require_alarm(self, alarm_id: UUID) -> Alarm:
        alarm = await self.alarms.get(alarm_id)
        if alarm is None:
            raise AlarmNotFoundError(f"alarm {alarm_id} was not found")
        return alarm

    @staticmethod
    def _status_of(alarm: Alarm) -> AlarmStatus:
        try:
            return AlarmStatus(alarm.status)
        except ValueError as exc:
            raise AlarmStateError(
                f"alarm {alarm.id} carries an unrecognised status",
                {"alarm_id": str(alarm.id), "current_status": alarm.status},
            ) from exc

    @staticmethod
    def _require_transition(alarm: Alarm, current: AlarmStatus, target: AlarmStatus) -> None:
        if is_alarm_transition_allowed(current, target):
            return
        raise AlarmStateError(
            f"alarm is {current.value}; {target.value} is not a legal next status",
            {
                "alarm_id": str(alarm.id),
                "current_status": current.value,
                "target_status": target.value,
                "allowed": describe_alarm_transitions(current),
            },
        )

    def _audit(self, *, action: str, resource: str, actor: str, details: dict[str, Any]) -> None:
        self.audit.add(
            trace_id=trace_id_context.get(),
            actor=actor,
            action=action,
            resource=resource,
            status="SUCCESS",
            details=details,
        )


__all__ = ["AlarmLifecycleService", "AlarmRuleService", "DEFAULT_ACTOR"]
