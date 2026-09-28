"""Audit event writer and, since Phase 6.13-C, audit query reader.

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

Phase 6.13-C adds the read side. The governance audit surface queries the same
table through :meth:`AuditRepository.query` and
:meth:`AuditRepository.security_summary`; there is one audit system, and its
governance view is a set of read methods on this repository, not a second
writer and not a second table.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent
from app.security.context import security_context

#: Actor recorded when there is no authenticated caller and no explicit value:
#: internal, system-initiated work such as a correlation pass or a scheduled job.
SYSTEM_ACTOR = "backend"

#: Hard ceiling on one audit page. Governance queries are for people reading a
#: trail, not for exports; a client that needs more pages through.
MAX_QUERY_LIMIT = 200


class AuditQueryFilters:
    """Optional equality filters for :meth:`AuditRepository.query`.

    ``actions`` narrows to a set of actions (the security-event view uses it
    to keep only security-boundary rows); it composes with the single-action
    filter, which wins when both are given.
    """

    __slots__ = (
        "action",
        "actions",
        "actor",
        "resource",
        "resource_id",
        "since",
        "status",
        "trace_id",
        "until",
    )

    def __init__(
        self,
        *,
        actor: str | None = None,
        action: str | None = None,
        actions: tuple[str, ...] | None = None,
        resource: str | None = None,
        resource_id: str | None = None,
        status: str | None = None,
        trace_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> None:
        self.actor = actor
        self.action = action
        self.actions = actions
        self.resource = resource
        self.resource_id = resource_id
        self.status = status
        self.trace_id = trace_id
        self.since = since
        self.until = until

    def _apply(self, statement: Select[Any]) -> Select[Any]:
        if self.actor is not None:
            statement = statement.where(AuditEvent.actor == self.actor)
        if self.action is not None:
            statement = statement.where(AuditEvent.action == self.action)
        elif self.actions is not None:
            statement = statement.where(AuditEvent.action.in_(self.actions))
        if self.resource is not None:
            statement = statement.where(AuditEvent.resource == self.resource)
        if self.resource_id is not None:
            statement = statement.where(AuditEvent.resource_id == self.resource_id)
        if self.status is not None:
            statement = statement.where(AuditEvent.status == self.status)
        if self.trace_id is not None:
            statement = statement.where(AuditEvent.trace_id == self.trace_id)
        if self.since is not None:
            statement = statement.where(AuditEvent.timestamp >= self.since)
        if self.until is not None:
            statement = statement.where(AuditEvent.timestamp < self.until)
        return statement


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
        resolved_details = dict(details) if details else {}
        # Phase 6.13-A: the legacy ``X-Actor`` header survives only as
        # metadata. It never overrides ``actor`` or ``actor_user_id``; it is
        # recorded so a pre-migration client's claim stays visible next to the
        # identity that actually acted.
        if (
            context is not None
            and context.legacy_actor is not None
            and "legacy_x_actor" not in resolved_details
        ):
            resolved_details["legacy_x_actor"] = context.legacy_actor
        self.session.add(
            AuditEvent(
                trace_id=trace_id,
                actor=resolved_actor or SYSTEM_ACTOR,
                actor_user_id=resolved_user_id,
                action=action,
                resource=resource,
                resource_id=resource_id,
                status=status,
                details=resolved_details,
                ip_address=resolved_ip,
                user_agent=resolved_agent,
            )
        )

    async def query(
        self,
        filters: AuditQueryFilters,
        *,
        limit: int = MAX_QUERY_LIMIT,
        offset: int = 0,
    ) -> tuple[list[AuditEvent], int]:
        """Return one page of audit rows, newest first, plus the total count.

        The newest-first ordering is the trail a compliance reviewer reads;
        the incident timeline, which reads oldest-first, keeps its own query
        and is untouched.
        """

        base = filters._apply(select(AuditEvent))
        total = await self.session.scalar(
            select(func.count()).select_from(base.order_by(None).subquery())
        )
        rows = list(
            await self.session.scalars(
                base.order_by(AuditEvent.timestamp.desc()).limit(limit).offset(offset)
            )
        )
        return rows, int(total or 0)

    async def summary(
        self,
        filters: AuditQueryFilters,
    ) -> dict[str, dict[str, int]]:
        """Aggregate counts by ``action`` then ``status`` for the filters.

        The security-event view and the compliance dashboard are built from
        this one aggregation; no separate summary table exists, so the numbers
        and the rows can never drift apart.
        """

        statement = filters._apply(
            select(
                AuditEvent.action,
                AuditEvent.status,
                func.count(),
            ).group_by(AuditEvent.action, AuditEvent.status)
        )
        counts: dict[str, dict[str, int]] = {}
        for action, status, count in await self.session.execute(statement):
            counts.setdefault(str(action), {})[str(status)] = int(count)
        return counts
