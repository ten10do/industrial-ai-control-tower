"""Industrial protocol adapter foundation."""

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
    SignalQuality,
    UnifiedTelemetry,
)
from adapters.opcua_adapter import OpcUaAdapter
from adapters.registry import AdapterRegistry, create_adapter, registry
from adapters.simulator_adapter import SimulatorAdapter

registry.register(ProtocolType.SIMULATOR, SimulatorAdapter)
registry.register(ProtocolType.OPC_UA, OpcUaAdapter)

__all__ = [
    "AdapterConfigurationError",
    "AdapterConnectionError",
    "AdapterError",
    "AdapterHealth",
    "AdapterReadError",
    "AdapterRegistry",
    "AdapterStatus",
    "IndustrialProtocolAdapter",
    "OpcUaAdapter",
    "ProtocolType",
    "SignalQuality",
    "SimulatorAdapter",
    "UnifiedTelemetry",
    "create_adapter",
    "registry",
]
