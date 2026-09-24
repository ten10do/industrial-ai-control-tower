"""Audit event writer.

One writer for the whole platform. Phase 6.12 extends it in two ways without
changing a single call site's behaviour:

* the four new columns (``actor_user_id``, ``ip_address``, ``user_agent``,
  ``resource_id``) are optional keyword arguments, so every existing caller
  keeps working untouched;
* when a caller does not state the actor, the writer falls back to the
  request-scoped :data:`app.security.context.security_context` before falling
  back to ``"backend"``. That is how an incident acknowledgement performed
  through an authenticated request starts recording *who* did it, even though
  the incident lifecycle service knows nothing about authentication.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent
from app.security.context import security_context

#: Actor recorded when there is no authenticated caller and no explicit value:
#: internal, system-initiated work such as a correlation pass or a scheduled job.
SYSTEM_ACTOR = "backend"


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
        actor: str | None = None,
        resource_id: str | None = None,
        actor_user_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        context = security_context.get()
        resolved_actor = actor
        if resolved_actor is None and context is not None:
            resolved_actor = context.actor
        resolved_user_id = actor_user_id
        if resolved_user_id is None and context is not None:
            resolved_user_id = context.actor_user_id
        resolved_ip = (
            ip_address
            if ip_address is not None
            else (context.ip_address if context is not None else None)
        )
        resolved_agent = (
            user_agent
            if user_agent is not None
            else (context.user_agent if context is not None else None)
        )
        self.session.add(
            AuditEvent(
                trace_id=trace_id,
                actor=resolved_actor or SYSTEM_ACTOR,
                actor_user_id=resolved_user_id,
                action=action,
                resource=resource,
                resource_id=resource_id,
                status=status,
                details=details or {},
                ip_address=resolved_ip,
                user_agent=resolved_agent,
            )
        )
