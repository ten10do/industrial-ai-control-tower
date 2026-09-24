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
from app.incidents.models import AlarmRule, IncidentAlarm
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
from app.security.models import (
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserStatus,
)
from app.security.org_models import (
    Area,
    DeviceScope,
    Organization,
    Plant,
    ScopeLevel,
    UserScope,
)

__all__ = [
    "AgentRun",
    "Alarm",
    "AlarmRule",
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
    "IncidentAlarm",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "MaintenancePlan",
    "ObservabilityMetric",
    "ObservabilityRun",
    "ObservabilityStep",
    "Permission",
    "RetrievalRun",
    "Role",
    "RolePermission",
    "Telemetry",
    "User",
    "UserRole",
    "UserStatus",
    "WorkOrder",
    "WorkflowRun",
    "Organization",
    "Plant",
    "Area",
    "UserScope",
    "DeviceScope",
    "ScopeLevel",
]
