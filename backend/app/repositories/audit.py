"""Audit event writer."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(
        self,
        *,
        trace_id: str,
        action: str,
        resource: str,
        status: str,
        details: dict[str, Any] | None = None,
        actor: str = "backend",
    ) -> None:
        self.session.add(
            AuditEvent(
                trace_id=trace_id,
                actor=actor,
                action=action,
                resource=resource,
                status=status,
                details=details or {},
            )
        )
