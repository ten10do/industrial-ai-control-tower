"""Typed failures raised by the industrial protocol gateway."""

from __future__ import annotations


class GatewayError(Exception):
    """Base class for gateway failures."""


class GatewayConfigurationError(GatewayError):
    """Raised when a device definition or gateway configuration is invalid."""


class GatewayStateError(GatewayError):
    """Raised when a lifecycle transition is not permitted."""


class TelemetryNormalizationError(GatewayError):
    """Raised when an adapter sample cannot satisfy the canonical contract."""
