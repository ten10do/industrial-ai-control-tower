"""Phase 6.7 industrial protocol gateway.

Public contract for declarative device onboarding, adapter lifecycle management,
and the read-only connectivity status surface.
"""

from app.gateway.config import is_secret_key, load_gateway_config, redact_secrets
from app.gateway.errors import (
    GatewayConfigurationError,
    GatewayError,
    GatewayStateError,
    TelemetryNormalizationError,
)
from app.gateway.gateway import IndustrialProtocolGateway
from app.gateway.ingestion import (
    DeviceRegistrationChecker,
    GatewayIngestionSink,
    IngestionOutcome,
    RegistrationChecker,
    TelemetrySink,
    telemetry_topic,
)
from app.gateway.models import (
    CANONICAL_SIGNAL_FIELDS,
    ConnectivitySummary,
    DeviceDefinition,
    DeviceState,
    DeviceStateDefinition,
    DeviceStatusRead,
    ModbusDeviceConfig,
    MqttDeviceConfig,
    OpcUaDeviceConfig,
    SimulatorDeviceConfig,
    StateRule,
)
from app.gateway.normalizer import resolve_state, to_canonical_body, to_canonical_payload
from app.gateway.registry import DeviceRegistry
from app.gateway.runtime import DeviceRuntime, RetryPolicy

__all__ = [
    "CANONICAL_SIGNAL_FIELDS",
    "ConnectivitySummary",
    "DeviceDefinition",
    "DeviceRegistrationChecker",
    "DeviceRegistry",
    "DeviceRuntime",
    "DeviceState",
    "DeviceStateDefinition",
    "DeviceStatusRead",
    "GatewayConfigurationError",
    "GatewayError",
    "GatewayIngestionSink",
    "GatewayStateError",
    "IndustrialProtocolGateway",
    "IngestionOutcome",
    "ModbusDeviceConfig",
    "MqttDeviceConfig",
    "OpcUaDeviceConfig",
    "RegistrationChecker",
    "RetryPolicy",
    "SimulatorDeviceConfig",
    "StateRule",
    "TelemetryNormalizationError",
    "TelemetrySink",
    "is_secret_key",
    "load_gateway_config",
    "redact_secrets",
    "resolve_state",
    "telemetry_topic",
    "to_canonical_body",
    "to_canonical_payload",
]
