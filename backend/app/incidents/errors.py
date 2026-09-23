"""Alarm lifecycle and correlation errors.

Each error carries a stable public code, an HTTP status, and optional structured
details, mirroring the ``app.assetconfig.errors`` family. The application
registers one handler for the whole family, so routes stay free of translation
boilerplate and every failure renders through the existing ``{"error": {...}}``
envelope with a trace id.
"""

from __future__ import annotations

from typing import Any


class AlarmLifecycleError(Exception):
    """Base class for alarm rule, lifecycle, and correlation failures."""

    code = "ALARM_LIFECYCLE_ERROR"
    status_code = 400

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}


class AlarmNotFoundError(AlarmLifecycleError):
    """The requested alarm instance does not exist."""

    code = "ALARM_NOT_FOUND"
    status_code = 404


class AlarmStateError(AlarmLifecycleError):
    """The requested status move is not declared legal for the current status."""

    code = "ALARM_STATE_INVALID"
    status_code = 409


class AlarmRuleNotFoundError(AlarmLifecycleError):
    """The requested alarm rule does not exist."""

    code = "ALARM_RULE_NOT_FOUND"
    status_code = 404


class AlarmRuleConflictError(AlarmLifecycleError):
    """An alarm rule with this identifier already exists."""

    code = "ALARM_RULE_CONFLICT"
    status_code = 409


class AlarmRuleValidationError(AlarmLifecycleError):
    """The alarm rule definition is not usable and must not be persisted."""

    code = "ALARM_RULE_INVALID"
    status_code = 422

    def __init__(self, message: str, errors: list[dict[str, str]] | None = None) -> None:
        super().__init__(message, {"errors": errors or []})
        self.errors = errors or []


__all__ = [
    "AlarmLifecycleError",
    "AlarmNotFoundError",
    "AlarmRuleConflictError",
    "AlarmRuleNotFoundError",
    "AlarmRuleValidationError",
    "AlarmStateError",
]
