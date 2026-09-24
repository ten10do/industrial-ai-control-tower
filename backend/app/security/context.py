"""Request-scoped security context.

The audit trail predates authentication: every row written before Phase 6.12
has an ``actor`` string and nothing else, because there was nothing else to
record. Rather than thread a principal parameter through the incident
lifecycle, the workflow engine, and the configuration applier, the identity of
the caller for the current request lives here and
:class:`app.repositories.audit.AuditRepository` reads it.

That keeps the business services untouched while making every audit row written
during an authenticated request carry the real actor, the actor's user id, the
source address, and the client description. It follows the same shape as
:mod:`app.core.context`, which already carries the trace id the same way.

The value is set inside the request task by the authentication dependency and
cleared for each request by the correlation middleware, so it can never leak
from one request into the next.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SecurityContext:
    """Who is calling, from where, with what client."""

    actor: str
    actor_user_id: UUID | None
    ip_address: str | None
    user_agent: str | None


security_context: ContextVar[SecurityContext | None] = ContextVar("security_context", default=None)
