"""Side-effect-free validation for device acquisition configurations.

The pipeline only inspects data. It never publishes, never touches the gateway,
never opens a connection, and never mutates the current published configuration.
No protocol connectivity probe is performed, so validating a definition cannot
contact a production endpoint.

Structural checks are delegated to the Phase 6.7 typed models. If a payload fails
the typed validator it is reported as a structured issue and can never be stored,
so the JSONB snapshot at rest is always a valid typed definition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from adapters.models import ProtocolType
from app.assetconfig.models import AssetType  # noqa: F401  (re-exported for callers)
from app.gateway.config import is_secret_key
from app.gateway.errors import GatewayConfigurationError
from app.gateway.models import CANONICAL_SIGNAL_FIELDS, DeviceDefinition
from app.gateway.registry import DeviceRegistry

DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND"
DEVICE_NOT_ACTIVE = "DEVICE_NOT_ACTIVE"
DEVICE_ID_MISMATCH = "DEVICE_ID_MISMATCH"
UNSUPPORTED_PROTOCOL = "UNSUPPORTED_PROTOCOL"
ENDPOINT_INVALID = "ENDPOINT_INVALID"
POLL_INTERVAL_INVALID = "POLL_INTERVAL_INVALID"
TIMEOUT_INVALID = "TIMEOUT_INVALID"
MISSING_SIGNAL = "MISSING_SIGNAL"
UNKNOWN_SIGNAL = "UNKNOWN_SIGNAL"
PROTOCOL_MAPPING_INVALID = "PROTOCOL_MAPPING_INVALID"
PROTOCOL_BLOCK_MISSING = "PROTOCOL_BLOCK_MISSING"
PROTOCOL_BLOCK_MISMATCH = "PROTOCOL_BLOCK_MISMATCH"
STATE_RULE_INVALID = "STATE_RULE_INVALID"
STATE_DEFINITION_INVALID = "STATE_DEFINITION_INVALID"
FIELD_REQUIRED = "FIELD_REQUIRED"
FIELD_INVALID = "FIELD_INVALID"
FIELD_UNKNOWN = "FIELD_UNKNOWN"
SECRET_MATERIAL_REJECTED = "SECRET_MATERIAL_REJECTED"
GATEWAY_INCOMPATIBLE = "GATEWAY_INCOMPATIBLE"


@dataclass(slots=True)
class ValidationOutcome:
    """Structured validation result."""

    valid: bool
    errors: list[dict[str, str]] = field(default_factory=list)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "checked_at": self.checked_at.isoformat(),
        }


def _issue(field_path: str, code: str, message: str) -> dict[str, str]:
    return {"field": field_path, "code": code, "message": message}


def _classify(message: str, error_type: str) -> str:
    lowered = message.lower()
    if "missing canonical signals" in lowered:
        return MISSING_SIGNAL
    if "unknown signals" in lowered:
        return UNKNOWN_SIGNAL
    if "must declare a" in lowered and "block" in lowered:
        return PROTOCOL_BLOCK_MISSING
    if "do not match protocol" in lowered:
        return PROTOCOL_BLOCK_MISMATCH
    if "opc.tcp://" in lowered:
        return ENDPOINT_INVALID
    if "must be finite" in lowered:
        return PROTOCOL_MAPPING_INVALID
    if "derived state rules" in lowered:
        return STATE_RULE_INVALID
    if error_type == "missing":
        return FIELD_REQUIRED
    if error_type == "extra_forbidden":
        return FIELD_UNKNOWN
    return FIELD_INVALID


def pydantic_issues(exc: ValidationError) -> list[dict[str, str]]:
    """Translate typed-model failures into structured issues.

    Public because the write path uses it too. A payload that the typed validator
    rejects must produce the same codes whether it is rejected on the way in or
    reported by ``/validate``; two classifiers would make the same mistake look
    like two different mistakes.
    """

    issues: list[dict[str, str]] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"])
        message = str(error["msg"])
        issues.append(_issue(location or "<root>", _classify(message, str(error["type"])), message))
    return issues


def _secret_issues(payload: Any, prefix: str = "") -> list[dict[str, str]]:
    """Report credential-shaped keys that carry a value."""

    issues: list[dict[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if is_secret_key(str(key)) and value not in (None, "", {}, []):
                issues.append(
                    _issue(
                        path,
                        SECRET_MATERIAL_REJECTED,
                        "credential material must not be stored in a configuration snapshot; "
                        "use an opaque secret reference instead",
                    )
                )
            issues.extend(_secret_issues(value, path))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            issues.extend(_secret_issues(item, f"{prefix}[{index}]"))
    return issues


def validate_configuration(
    *,
    device_id: str,
    payload: dict[str, Any],
    device_status: str | None,
) -> ValidationOutcome:
    """Validate one candidate configuration without any side effect.

    ``device_status`` is ``None`` when the device is not registered. A device that
    is not registered, or that is not ``ACTIVE``, cannot be onboarded.
    """

    errors: list[dict[str, str]] = []
    errors.extend(_secret_issues(payload))

    if device_status is None:
        errors.append(
            _issue("device_id", DEVICE_NOT_FOUND, f"device '{device_id}' is not registered")
        )

    definition: DeviceDefinition | None = None
    try:
        definition = DeviceDefinition.model_validate(payload)
    except ValidationError as exc:
        errors.extend(pydantic_issues(exc))

    if definition is not None:
        if definition.device_id != device_id:
            errors.append(
                _issue(
                    "device_id",
                    DEVICE_ID_MISMATCH,
                    f"payload device_id '{definition.device_id}' does not match "
                    f"the target device '{device_id}'",
                )
            )
        if definition.protocol not in set(ProtocolType):
            errors.append(
                _issue(
                    "protocol",
                    UNSUPPORTED_PROTOCOL,
                    f"protocol '{definition.protocol}' is not supported",
                )
            )
        if definition.polled and definition.endpoint is None:
            errors.append(
                _issue(
                    "endpoint",
                    ENDPOINT_INVALID,
                    f"protocol '{definition.protocol.value}' requires a connection endpoint",
                )
            )
        if not (100 <= definition.poll_interval_ms <= 3_600_000):
            errors.append(
                _issue(
                    "poll_interval_ms",
                    POLL_INTERVAL_INVALID,
                    "poll interval must be between 100 and 3600000 milliseconds",
                )
            )
        if definition.modbus_tcp is not None and definition.modbus_tcp.timeout_seconds <= 0:
            errors.append(
                _issue("modbus_tcp.timeout_seconds", TIMEOUT_INVALID, "timeout must be positive")
            )
        if definition.opc_ua is not None and definition.opc_ua.timeout_seconds <= 0:
            errors.append(
                _issue("opc_ua.timeout_seconds", TIMEOUT_INVALID, "timeout must be positive")
            )
        if not definition.state.operating_state or not definition.state.fault_state:
            errors.append(
                _issue(
                    "state",
                    STATE_DEFINITION_INVALID,
                    "operating_state and fault_state must both be declared",
                )
            )
        errors.extend(_gateway_compatibility(definition))

    if device_status is not None and device_status != "ACTIVE":
        errors.append(
            _issue(
                "device_id",
                DEVICE_NOT_ACTIVE,
                f"device '{device_id}' has status '{device_status}'; acquisition requires ACTIVE",
            )
        )

    return ValidationOutcome(valid=not errors, errors=errors)


def _gateway_compatibility(definition: DeviceDefinition) -> list[dict[str, str]]:
    """Prove the definition can be registered into a gateway device registry."""

    registry = DeviceRegistry()
    try:
        registry.register(definition)
    except (GatewayConfigurationError, ValueError) as exc:
        return [_issue("configuration", GATEWAY_INCOMPATIBLE, str(exc))]
    return []


def canonical_signals() -> tuple[str, ...]:
    """Expose the canonical signal vocabulary for callers and tests."""

    return CANONICAL_SIGNAL_FIELDS
