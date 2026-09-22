"""Adapter registry and typed failure tests."""

from adapters.base import IndustrialProtocolAdapter
from adapters.exceptions import (
    AdapterConfigurationError,
    AdapterConnectionError,
    AdapterError,
    AdapterReadError,
)
from adapters.models import (
    AdapterHealth,
    AdapterStatus,
    ProtocolType,
    UnifiedTelemetry,
)
from adapters.registry import AdapterRegistry, create_adapter
from adapters.simulator_adapter import SimulatorAdapter


class ExampleAdapter(IndustrialProtocolAdapter):
    def __init__(self, label: str) -> None:
        self.label = label

    @property
    def protocol(self) -> ProtocolType:
        return ProtocolType.MQTT

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def read(self) -> UnifiedTelemetry:
        raise AdapterReadError("No example source configured.")

    def health(self) -> AdapterHealth:
        return AdapterHealth(protocol=self.protocol, status=AdapterStatus.DISCONNECTED)


def test_registry_registers_and_creates_adapter() -> None:
    local_registry = AdapterRegistry()
    local_registry.register(ProtocolType.MQTT, ExampleAdapter)

    adapter = local_registry.create("mqtt", label="line-1")

    assert isinstance(adapter, ExampleAdapter)
    assert adapter.label == "line-1"


def test_shared_registry_exposes_simulator_adapter() -> None:
    adapter = create_adapter("simulator", source=dict)

    assert isinstance(adapter, SimulatorAdapter)


def test_registry_uses_configuration_errors() -> None:
    local_registry = AdapterRegistry()
    local_registry.register(ProtocolType.MQTT, ExampleAdapter)

    try:
        local_registry.register(ProtocolType.MQTT, ExampleAdapter)
    except AdapterConfigurationError:
        pass
    else:
        raise AssertionError("duplicate registration must fail")

    try:
        local_registry.create("opcua")
    except AdapterConfigurationError:
        pass
    else:
        raise AssertionError("unregistered protocol must fail")


def test_adapter_exceptions_share_typed_base() -> None:
    assert issubclass(AdapterConnectionError, AdapterError)
    assert issubclass(AdapterReadError, AdapterError)
    assert issubclass(AdapterConfigurationError, AdapterError)
