"""Security-boundary audit writer.

Phase 6.12 adds four columns to the existing ``audit_events`` table and one
convention for the rows the security layer writes.

The convention, from the phase spec::

    {"actor": "user123", "action": "INCIDENT_RESOLVE", "resource": "incident",
     "resource_id": "xxx", "status": "SUCCESS"}

Rows written before this phase use ``resource`` to carry the resource
*identifier* (an incident uuid, or ``device-config:<device>``), because that is
what the incident timeline and the configuration audit both query. That shape
is preserved untouched: rewriting historical rows to fit a new convention would
invalidate the evidence the earlier phases produced.

So the two coexist, and the split is explicit rather than accidental: security
boundary events (authentication, authorization) use the unified shape with
``resource`` naming the type and ``resource_id`` naming the instance. Business
events keep their historical shape and gain the new identity columns, which is
what makes "who acknowledged this incident" answerable for the first time.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import trace_id_context
from app.repositories.audit import AuditRepository
from app.security.context import SecurityContext, security_context

AUTH_RESOURCE = "auth"
PERMISSION_RESOURCE = "permission"

ACTION_LOGIN = "AUTH_LOGIN"
ACTION_LOGOUT = "AUTH_LOGOUT"
ACTION_REGISTER = "AUTH_REGISTER"
ACTION_PERMISSION_DENIED = "PERMISSION_DENIED"
#: Phase 6.13-B: a device-scoped request refused by the Scope Policy layer.
ACTION_SCOPE_DENIED = "SCOPE_DENIED"

STATUS_SUCCESS = "SUCCESS"
STATUS_FAILURE = "FAILURE"
STATUS_DENIED = "DENIED"


async def record_security_event(
    session: AsyncSession,
    *,
    action: str,
    resource: str,
    resource_id: str | None,
    status: str,
    details: dict[str, Any] | None = None,
    actor: str | None = None,
    actor_user_id: UUID | None = None,
    context: SecurityContext | None = None,
    commit: bool = True,
) -> None:
    """Write one audit row for a security event.

    Explicit arguments win over the request context, which is what lets the
    login route attribute a successful authentication to the user it just
    verified rather than to whoever the request context happens to describe.
    """

    active = context if context is not None else security_context.get()
    resolved_actor = actor or (active.actor if active is not None else "anonymous")
    resolved_user_id = (
        actor_user_id
        if actor_user_id is not None
        else (active.actor_user_id if active is not None else None)
    )
    AuditRepository(session).add(
        trace_id=trace_id_context.get(),
        actor=resolved_actor,
        actor_user_id=resolved_user_id,
        action=action,
        resource=resource,
        resource_id=resource_id,
        status=status,
        details=details or {},
        ip_address=active.ip_address if active is not None else None,
        user_agent=active.user_agent if active is not None else None,
    )
    if commit:
        await session.commit()
