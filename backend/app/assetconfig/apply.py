"""Controlled application of a published configuration to the gateway runtime.

Publishing a configuration and applying it are deliberately two separate facts.
The database records what should run. The gateway records what does run. When
they disagree, the disagreement is reported instead of hidden.

Applying one device never touches another device runtime, and a failed
application leaves the previously running runtime in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.gateway.gateway import ApplyResult, IndustrialProtocolGateway
from app.gateway.models import DeviceDefinition


@dataclass(frozen=True, slots=True)
class ApplyOutcome:
    """Normalized result of a runtime application attempt."""

    applied: bool
    applied_version: int | None
    error: str | None = None
    runtime_state: str | None = None


class DefinitionApplier(Protocol):
    """Apply one device definition to whatever owns the runtime."""

    @property
    def available(self) -> bool:
        """Return whether a runtime owner exists in this process."""

    async def apply(self, definition: DeviceDefinition, *, version: int | None) -> ApplyOutcome:
        """Apply the definition and report whether it actually took effect."""

    def applied_version(self, device_id: str) -> int | None:
        """Return the version the runtime is running, when known."""

    def runtime_state(self, device_id: str) -> str | None:
        """Return the runtime lifecycle state, when known."""


class GatewayDefinitionApplier:
    """Apply definitions through the Phase 6.7 industrial protocol gateway."""

    def __init__(self, gateway: IndustrialProtocolGateway) -> None:
        self._gateway = gateway

    @property
    def available(self) -> bool:
        return self._gateway.enabled

    async def apply(self, definition: DeviceDefinition, *, version: int | None) -> ApplyOutcome:
        result: ApplyResult = await self._gateway.apply_device_definition(
            definition, version=version
        )
        return ApplyOutcome(
            applied=result.applied,
            applied_version=result.version if result.applied else None,
            error=result.error,
            runtime_state=result.state.value,
        )

    def applied_version(self, device_id: str) -> int | None:
        return self._gateway.applied_version(device_id)

    def runtime_state(self, device_id: str) -> str | None:
        gateway = self._gateway
        try:
            return gateway.status(device_id).state.value
        except Exception:
            return None


class UnavailableApplier:
    """Represents a process with no gateway runtime owner.

    Applying is refused rather than silently reported as success, so the API can
    answer honestly when the gateway is disabled.
    """

    @property
    def available(self) -> bool:
        return False

    async def apply(self, definition: DeviceDefinition, *, version: int | None) -> ApplyOutcome:
        return ApplyOutcome(
            applied=False,
            applied_version=None,
            error="gateway runtime is not available in this process",
        )

    def applied_version(self, device_id: str) -> int | None:
        return None

    def runtime_state(self, device_id: str) -> str | None:
        return None
