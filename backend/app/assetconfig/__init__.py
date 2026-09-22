"""Asset and Device Configuration Management (Phase 6.8).

Persistent asset hierarchy, versioned device acquisition configuration, a draft /
validate / publish lifecycle, and controlled application of a published version to
the Phase 6.7 gateway runtime.

The layer manages metadata and telemetry acquisition configuration only. It adds no
PLC control, no Modbus write, no OPC UA write, no remote command, and no actuation.
Gateway start and stop continue to mean software acquisition lifecycle.

This package initialiser intentionally re-exports only the dependency-free models
and errors. ``app.models`` imports ``app.assetconfig.models`` while it is still
initialising, so importing ``service``, ``apply``, ``contracts``, ``repository``, or
``source`` here would create an import cycle back through ``app.models``. Import
those modules directly instead.
"""

from app.assetconfig.errors import (
    ApplyUnavailableError,
    AssetConfigError,
    AssetHierarchyError,
    AssetInUseError,
    AssetNotFoundError,
    ConfigurationConflictError,
    ConfigurationImmutableError,
    ConfigurationNotFoundError,
    ConfigurationStateError,
    ConfigurationValidationError,
    DeviceNotFoundError,
)
from app.assetconfig.models import (
    ASSET_PARENT_RULES,
    ApplyStatus,
    AssetNode,
    AssetType,
    ConfigurationSource,
    ConfigurationStatus,
    DeviceConfiguration,
    DeviceConfigurationRuntimeStatus,
)

__all__ = [
    "ASSET_PARENT_RULES",
    "ApplyStatus",
    "ApplyUnavailableError",
    "AssetConfigError",
    "AssetHierarchyError",
    "AssetInUseError",
    "AssetNode",
    "AssetNotFoundError",
    "AssetType",
    "ConfigurationConflictError",
    "ConfigurationImmutableError",
    "ConfigurationNotFoundError",
    "ConfigurationSource",
    "ConfigurationStateError",
    "ConfigurationStatus",
    "ConfigurationValidationError",
    "DeviceConfiguration",
    "DeviceConfigurationRuntimeStatus",
    "DeviceNotFoundError",
]
