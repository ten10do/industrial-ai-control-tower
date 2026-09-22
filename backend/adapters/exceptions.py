"""Typed failures raised by industrial protocol adapters."""


class AdapterError(Exception):
    """Base class for all adapter failures."""


class AdapterConnectionError(AdapterError):
    """Raised when an adapter cannot establish or use a connection."""


class AdapterReadError(AdapterError):
    """Raised when a protocol payload cannot be read or normalized."""


class AdapterConfigurationError(AdapterError):
    """Raised for invalid adapter configuration or registration."""
