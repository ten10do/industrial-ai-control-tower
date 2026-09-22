"""Registry of validated gateway device definitions."""

from __future__ import annotations

from collections.abc import Sequence

from app.gateway.errors import GatewayConfigurationError
from app.gateway.models import DeviceDefinition


class DeviceRegistry:
    """Hold device definitions keyed by device id, preserving load order.

    Loading is atomic: a batch containing a duplicate id, or an id already present,
    is rejected before anything is registered.
    """

    def __init__(self) -> None:
        self._devices: dict[str, DeviceDefinition] = {}

    def register(self, definition: DeviceDefinition) -> None:
        """Register one definition, rejecting duplicates."""

        if definition.device_id in self._devices:
            raise GatewayConfigurationError(
                f"device '{definition.device_id}' is already registered"
            )
        self._devices[definition.device_id] = definition

    def load(self, definitions: Sequence[DeviceDefinition]) -> None:
        """Register a batch of definitions atomically."""

        seen: set[str] = set()
        duplicates: list[str] = []
        for definition in definitions:
            if definition.device_id in seen or definition.device_id in self._devices:
                duplicates.append(definition.device_id)
            seen.add(definition.device_id)
        if duplicates:
            raise GatewayConfigurationError(
                "duplicate device ids: " + ", ".join(sorted(set(duplicates)))
            )
        for definition in definitions:
            self._devices[definition.device_id] = definition

    def get(self, device_id: str) -> DeviceDefinition:
        """Return one definition or raise."""

        try:
            return self._devices[device_id]
        except KeyError as exc:
            raise GatewayConfigurationError(f"device '{device_id}' is not registered") from exc

    def find(self, device_id: str) -> DeviceDefinition | None:
        """Return one definition, or ``None`` when it is not registered."""

        return self._devices.get(device_id)

    def list_definitions(self) -> list[DeviceDefinition]:
        """Return every definition in load order."""

        return list(self._devices.values())

    def enabled(self) -> list[DeviceDefinition]:
        """Return the definitions the gateway should run."""

        return [definition for definition in self._devices.values() if definition.enabled]

    def __len__(self) -> int:
        return len(self._devices)

    def __contains__(self, device_id: object) -> bool:
        return device_id in self._devices
