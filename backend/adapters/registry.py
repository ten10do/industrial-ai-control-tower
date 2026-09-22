"""Registry-backed construction of industrial protocol adapters."""

from typing import Any

from adapters.base import IndustrialProtocolAdapter
from adapters.exceptions import AdapterConfigurationError
from adapters.models import ProtocolType


class AdapterRegistry:
    """Map protocol identifiers to adapter implementations."""

    def __init__(self) -> None:
        self._adapter_types: dict[ProtocolType, type[IndustrialProtocolAdapter]] = {}

    def register(
        self,
        protocol: ProtocolType,
        adapter_type: type[IndustrialProtocolAdapter],
    ) -> None:
        if not issubclass(adapter_type, IndustrialProtocolAdapter):
            raise AdapterConfigurationError(
                f"Adapter for {protocol.value} must implement IndustrialProtocolAdapter."
            )
        if protocol in self._adapter_types:
            raise AdapterConfigurationError(f"Adapter already registered for {protocol.value}.")
        self._adapter_types[protocol] = adapter_type

    def create(
        self, protocol: ProtocolType | str, **configuration: Any
    ) -> IndustrialProtocolAdapter:
        try:
            normalized = protocol if isinstance(protocol, ProtocolType) else ProtocolType(protocol)
        except ValueError as exc:
            raise AdapterConfigurationError(f"Unsupported protocol: {protocol}.") from exc
        adapter_type = self._adapter_types.get(normalized)
        if adapter_type is None:
            raise AdapterConfigurationError(f"No adapter registered for {normalized.value}.")
        try:
            return adapter_type(**configuration)
        except AdapterConfigurationError:
            raise
        except (TypeError, ValueError) as exc:
            raise AdapterConfigurationError(
                f"Invalid configuration for {normalized.value}."
            ) from exc


registry = AdapterRegistry()


def create_adapter(protocol: ProtocolType | str, **configuration: Any) -> IndustrialProtocolAdapter:
    """Create an adapter from the shared protocol registry."""

    return registry.create(protocol, **configuration)
