"""Asset and device configuration request and response contracts.

The configuration payload is the existing Phase 6.7 ``DeviceDefinition`` model,
reused verbatim. No second definition schema is introduced, so a stored snapshot
can always be rebuilt into the exact typed object the gateway already consumes.
A stored payload that does not satisfy the typed validator can never reach the
database, because every write path parses it first.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.assetconfig.models import ApplyStatus, AssetType
from app.gateway.models import DeviceDefinition

__all__ = [
    "ApplyStatus",
    "AssetNodeCreate",
    "AssetNodeRead",
    "AssetTreeRead",
    "AssetTreeNode",
    "AuditEventRead",
    "ConfigurationDetailRead",
    "ConfigurationStatusRead",
    "ConfigurationSummaryRead",
    "DeviceDefinition",
    "DeviceSummaryRead",
    "PublishResultRead",
    "ValidationIssue",
    "ValidationResultRead",
]


class AssetNodeCreate(BaseModel):
    """Create one asset node."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    asset_type: AssetType
    parent_id: UUID | None = None
    description: str = Field(default="", max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetNodeRead(BaseModel):
    """One asset node with its direct device count."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    asset_type: str
    parent_id: UUID | None
    description: str
    metadata: dict[str, Any] = Field(validation_alias="node_metadata")
    device_count: int = 0
    created_at: datetime
    updated_at: datetime


class DeviceSummaryRead(BaseModel):
    """One device master row enriched with its configuration state.

    Identity and master data come from the existing ``devices`` table. Protocol,
    versions, and apply status come from the configuration tables. The two are
    kept separate on purpose: master data is not versioned, configuration is.
    """

    model_config = ConfigDict(extra="forbid")

    device_id: str
    name: str
    device_type: str
    status: str
    asset_node_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    protocol: str | None = None
    published_version: int | None = None
    applied_version: int | None = None
    apply_status: ApplyStatus = ApplyStatus.PENDING
    in_sync: bool = False


class AssetTreeNode(BaseModel):
    """One node in the rendered hierarchy."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    asset_type: str
    parent_id: UUID | None = None
    description: str = ""
    devices: list[DeviceSummaryRead] = Field(default_factory=list)
    children: list[AssetTreeNode] = Field(default_factory=list)


class AssetTreeRead(BaseModel):
    """Full hierarchy plus devices that are not attached to any node."""

    model_config = ConfigDict(extra="forbid")

    sites: list[AssetTreeNode] = Field(default_factory=list)
    unassigned_devices: list[DeviceSummaryRead] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    """One structured validation problem."""

    model_config = ConfigDict(extra="forbid")

    field: str
    code: str
    message: str


class ValidationResultRead(BaseModel):
    """Structured outcome of the validation pipeline."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    checked_at: datetime | None = None


class ConfigurationSummaryRead(BaseModel):
    """One row in a device's configuration history."""

    model_config = ConfigDict(from_attributes=True)

    version: int
    status: str
    protocol: str
    created_by: str
    created_at: datetime
    validated_at: datetime | None = None
    published_at: datetime | None = None
    archived_at: datetime | None = None


class ConfigurationDetailRead(BaseModel):
    """One configuration version including its snapshot."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    device_id: str
    version: int
    status: str
    protocol: str
    configuration: dict[str, Any]
    created_by: str
    validation_result: dict[str, Any] = Field(default_factory=dict)
    validation_error: str | None = None
    created_at: datetime
    updated_at: datetime
    validated_at: datetime | None = None
    published_at: datetime | None = None
    archived_at: datetime | None = None


class ConfigurationStatusRead(BaseModel):
    """Desired versus applied configuration for one device.

    ``desired_version`` is the published version the device should be running.
    ``applied_version`` is the version the gateway actually started. When they
    differ, ``apply_status`` explains why and ``in_sync`` is false, so a failed
    application is never presented as a success.
    """

    model_config = ConfigDict(from_attributes=True)

    device_id: str
    desired_version: int | None = None
    applied_version: int | None = None
    apply_status: ApplyStatus = ApplyStatus.PENDING
    source: str = "none"
    last_apply_at: datetime | None = None
    last_apply_error: str | None = None
    in_sync: bool = False
    protocol: str | None = None
    runtime_state: str | None = None


class AuditEventRead(BaseModel):
    """One configuration lifecycle audit record."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    device_id: str
    event_type: str
    config_version: int | None = None
    timestamp: datetime
    actor: str
    status: str
    summary: str = ""


class PublishResultRead(BaseModel):
    """Outcome of a publish request.

    The published version and the runtime application are reported separately,
    because the database can hold a published version while the gateway failed to
    apply it. ``status.in_sync`` is false in that case, so a failed application is
    never presented as a success.
    """

    model_config = ConfigDict(extra="forbid")

    configuration: ConfigurationDetailRead
    status: ConfigurationStatusRead
