"""Configuration lifecycle audit events.

Configuration events are ordinary audit events. They reuse the existing
``audit_events`` table and the existing ``AuditRepository`` writer, with a
namespaced resource key per device. No second audit store is introduced, so an
operator still has exactly one place to look for evidence.

Only safe metadata is recorded. No credential value, token, or private key can
reach the audit payload, because configuration snapshots cannot contain one.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.assetconfig.repository import CONFIG_AUDIT_RESOURCE_PREFIX, config_audit_resource
from app.core.context import trace_id_context
from app.models import AuditEvent
from app.repositories.audit import AuditRepository

DRAFT_CREATED = "CONFIG_DRAFT_CREATED"
DRAFT_UPDATED = "CONFIG_DRAFT_UPDATED"
DRAFT_DELETED = "CONFIG_DRAFT_DELETED"
VALIDATED = "CONFIG_VALIDATED"
PUBLISHED = "CONFIG_PUBLISHED"
ARCHIVED = "CONFIG_ARCHIVED"
ROLLBACK_DRAFT_CREATED = "CONFIG_ROLLBACK_DRAFT_CREATED"
APPLY_SUCCEEDED = "CONFIG_APPLY_SUCCEEDED"
APPLY_FAILED = "CONFIG_APPLY_FAILED"
APPLY_PENDING = "CONFIG_APPLY_PENDING"

CONFIGURATION_EVENT_TYPES: tuple[str, ...] = (
    DRAFT_CREATED,
    DRAFT_UPDATED,
    DRAFT_DELETED,
    VALIDATED,
    PUBLISHED,
    ARCHIVED,
    ROLLBACK_DRAFT_CREATED,
    APPLY_SUCCEEDED,
    APPLY_FAILED,
    APPLY_PENDING,
)


class ConfigurationAuditWriter:
    """Write configuration lifecycle events through the existing audit writer."""

    def __init__(self, session: AsyncSession) -> None:
        self._audit = AuditRepository(session)

    def record(
        self,
        *,
        device_id: str,
        event_type: str,
        version: int | None = None,
        status: str = "SUCCESS",
        summary: str = "",
        actor: str = "system",
        extra: dict[str, Any] | None = None,
    ) -> None:
        details: dict[str, Any] = {
            "device_id": device_id,
            "config_version": version,
            "summary": summary,
        }
        if extra:
            details.update(extra)
        self._audit.add(
            trace_id=trace_id_context.get(),
            action=event_type,
            resource=config_audit_resource(device_id),
            status=status,
            actor=actor,
            details=details,
        )


def audit_event_to_read(event: AuditEvent) -> dict[str, Any]:
    """Project one audit row onto the configuration audit read contract."""

    details = event.details or {}
    device_id = str(details.get("device_id") or "")
    if not device_id and event.resource.startswith(CONFIG_AUDIT_RESOURCE_PREFIX):
        device_id = event.resource[len(CONFIG_AUDIT_RESOURCE_PREFIX) :]
    version = details.get("config_version")
    return {
        "event_id": event.id,
        "device_id": device_id,
        "event_type": event.action,
        "config_version": int(version) if isinstance(version, int) else None,
        "timestamp": event.timestamp,
        "actor": event.actor,
        "status": event.status,
        "summary": str(details.get("summary") or ""),
    }
