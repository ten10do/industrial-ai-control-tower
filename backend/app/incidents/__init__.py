"""Alarm Lifecycle and Incident Correlation (Phase 6.9-A).

Raises the alarm from a per-sample rule trigger record to an active condition
lifecycle instance, promotes the two hardcoded thresholds into a declarative rule
registry, and lays the relation and lookup that will later carry alarm evidence
into an incident.

The layer manages condition state and rule metadata only. It adds no PLC control,
no Modbus write, no OPC UA write, no remote command, and no actuation. Rule
evaluation reads telemetry and writes alarm state; it never touches a device and
it never calls a model.

Phase 6.9-A deliberately contains no automatic alarm to incident path. The
``incident_alarms`` relation and ``find_related_alarm`` exist so that the
correlation stage can be built on top of them later.

This package initialiser intentionally re-exports only the dependency-free
modules. ``app.models`` imports ``app.incidents.models`` while it is still
initialising, so importing ``service``, ``repository``, ``correlation``,
``rules``, ``contracts``, or ``api`` here would create an import cycle back
through ``app.models``. Import those modules directly instead.
"""

from app.incidents.errors import (
    AlarmLifecycleError,
    AlarmNotFoundError,
    AlarmRuleConflictError,
    AlarmRuleNotFoundError,
    AlarmRuleValidationError,
    AlarmStateError,
)
from app.incidents.models import (
    RULE_OPERATORS,
    RULE_PRIORITIES,
    RULE_SEVERITIES,
    RULE_SIGNAL_NAMES,
    AlarmRule,
    IncidentAlarm,
)
from app.incidents.states import (
    ALARM_TRANSITIONS,
    OPEN_ALARM_STATUSES,
    SEVERITY_ORDER,
    AlarmPriority,
    AlarmSeverity,
    AlarmStatus,
    describe_alarm_transitions,
    is_alarm_transition_allowed,
)

__all__ = [
    "ALARM_TRANSITIONS",
    "OPEN_ALARM_STATUSES",
    "RULE_OPERATORS",
    "RULE_PRIORITIES",
    "RULE_SEVERITIES",
    "RULE_SIGNAL_NAMES",
    "SEVERITY_ORDER",
    "AlarmLifecycleError",
    "AlarmNotFoundError",
    "AlarmPriority",
    "AlarmRule",
    "AlarmRuleConflictError",
    "AlarmRuleNotFoundError",
    "AlarmRuleValidationError",
    "AlarmSeverity",
    "AlarmStateError",
    "AlarmStatus",
    "IncidentAlarm",
    "describe_alarm_transitions",
    "is_alarm_transition_allowed",
]
