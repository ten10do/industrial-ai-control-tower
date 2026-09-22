"""Strict YAML loading for declarative device definitions.

This is the only configuration loader in the gateway. It is deliberately strict:
unknown top-level keys, unknown protocol blocks, unsupported versions, partial
signal coverage, and duplicate device ids are all rejected with a precise message
rather than being silently ignored.

Secret handling: no device definition in this phase carries credentials, because
every adapter is read-only and unauthenticated. The redaction helper exists so that
future credential-bearing fields cannot leak through the connectivity API or logs.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.gateway.errors import GatewayConfigurationError
from app.gateway.models import DeviceDefinition

SUPPORTED_CONFIG_VERSION: Final[int] = 1

SECRET_KEY_MARKERS: Final[tuple[str, ...]] = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "api_key",
    "apikey",
    "private_key",
)

REDACTED: Final[str] = "***REDACTED***"


def is_secret_key(key: str) -> bool:
    """Return whether a configuration key name denotes a credential."""

    lowered = key.lower()
    return any(marker in lowered for marker in SECRET_KEY_MARKERS)


def redact_secrets(value: Any) -> Any:
    """Recursively replace credential-bearing values with a marker."""

    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if is_secret_key(str(key)) else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact_secrets(item) for item in value]
    return value


class GatewayConfig(BaseModel):
    """Top-level gateway configuration document."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=SUPPORTED_CONFIG_VERSION)
    devices: list[DeviceDefinition] = Field(default_factory=list)


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "<root>"
        parts.append(f"{location}: {error['msg']}")
    return "invalid gateway configuration -> " + "; ".join(parts)


def load_gateway_config(path: Path) -> list[DeviceDefinition]:
    """Read and validate a gateway configuration file.

    Raises:
        GatewayConfigurationError: when the file is missing, unreadable, malformed,
            or fails strict validation.
    """

    if not path.exists():
        raise GatewayConfigurationError(f"gateway configuration file was not found: {path.name}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise GatewayConfigurationError(
            f"gateway configuration file could not be read: {path.name}"
        ) from exc
    except yaml.YAMLError as exc:
        raise GatewayConfigurationError(
            f"gateway configuration file is not valid YAML: {path.name}"
        ) from exc
    if raw is None:
        raise GatewayConfigurationError("gateway configuration is empty")
    if not isinstance(raw, dict):
        raise GatewayConfigurationError("gateway configuration must be a mapping")
    try:
        config = GatewayConfig.model_validate(raw)
    except ValidationError as exc:
        raise GatewayConfigurationError(_format_validation_error(exc)) from exc
    if config.version != SUPPORTED_CONFIG_VERSION:
        raise GatewayConfigurationError(
            f"unsupported gateway configuration version: {config.version}"
        )
    return config.devices
