"""Asset and device configuration errors.

Each error carries a stable public code, an HTTP status, and optional structured
details. The application registers one handler for the whole family, so routes stay
free of translation boilerplate and every failure renders through the existing
``{"error": {...}}`` envelope with a trace id.
"""

from __future__ import annotations

from typing import Any


class AssetConfigError(Exception):
    """Base class for asset and configuration management failures."""

    code = "ASSET_CONFIGURATION_ERROR"
    status_code = 400

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}


class AssetNotFoundError(AssetConfigError):
    """The requested asset node does not exist."""

    code = "ASSET_NOT_FOUND"
    status_code = 404


class DeviceNotFoundError(AssetConfigError):
    """The requested device master record does not exist."""

    code = "DEVICE_NOT_FOUND"
    status_code = 404


class AssetHierarchyError(AssetConfigError):
    """The requested asset relationship violates the hierarchy rules."""

    code = "ASSET_HIERARCHY_INVALID"
    status_code = 422


class AssetInUseError(AssetConfigError):
    """The asset node still has children or attached devices."""

    code = "ASSET_IN_USE"
    status_code = 409


class DeviceNotAttachedError(AssetConfigError):
    """The device is not attached to the asset node named in the request."""

    code = "DEVICE_NOT_ATTACHED"
    status_code = 409


class ConfigurationNotFoundError(AssetConfigError):
    """The requested configuration version does not exist."""

    code = "CONFIGURATION_NOT_FOUND"
    status_code = 404


class ConfigurationImmutableError(AssetConfigError):
    """A published or archived configuration cannot be edited."""

    code = "CONFIGURATION_IMMUTABLE"
    status_code = 409


class ConfigurationConflictError(AssetConfigError):
    """A concurrent request invalidated this operation."""

    code = "CONFIGURATION_CONFLICT"
    status_code = 409


class ConfigurationValidationError(AssetConfigError):
    """The configuration failed validation and must not be published."""

    code = "CONFIGURATION_VALIDATION_FAILED"
    status_code = 422

    def __init__(self, message: str, errors: list[dict[str, str]] | None = None) -> None:
        super().__init__(message, {"errors": errors or []})
        self.errors = errors or []


class ConfigurationStateError(AssetConfigError):
    """The operation is not legal for the current configuration status."""

    code = "CONFIGURATION_STATE_INVALID"
    status_code = 409


class ApplyUnavailableError(AssetConfigError):
    """The gateway is disabled, so no runtime application can be attempted."""

    code = "APPLY_UNAVAILABLE"
    status_code = 503
