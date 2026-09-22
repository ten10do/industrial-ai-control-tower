"""Database models.

Every ORM model must be exported here. Alembic autogenerate and the schema-drift
check compare against ``Base.metadata``, and a model that is not imported is
invisible to that comparison.
"""

from app.assetconfig.models import (
    ApplyStatus,
    AssetNode,
    AssetType,
    ConfigurationSource,
    ConfigurationStatus,
    DeviceConfiguration,
    DeviceConfigurationRuntimeStatus,
)
from app.models.entities import (
    AgentRun,
    Alarm,
    Approval,
    AuditEvent,
    Device,
    Diagnosis,
    Evidence,
    Incident,
    KnowledgeChunk,
    KnowledgeDocument,
    MaintenancePlan,
    RetrievalRun,
    Telemetry,
    WorkflowRun,
    WorkOrder,
)
from app.observability.models import (
    ObservabilityMetric,
    ObservabilityRun,
    ObservabilityStep,
)

__all__ = [
    "AgentRun",
    "Alarm",
    "ApplyStatus",
    "Approval",
    "AssetNode",
    "AssetType",
    "AuditEvent",
    "ConfigurationSource",
    "ConfigurationStatus",
    "Device",
    "DeviceConfiguration",
    "DeviceConfigurationRuntimeStatus",
    "Diagnosis",
    "Evidence",
    "Incident",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "MaintenancePlan",
    "ObservabilityMetric",
    "ObservabilityRun",
    "ObservabilityStep",
    "RetrievalRun",
    "Telemetry",
    "WorkOrder",
    "WorkflowRun",
]
