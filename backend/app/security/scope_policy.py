"""Scope-aware authorization (Phase 6.13-B).

Every scope decision in the platform is made here. A route never answers "may
this caller touch this device?" by querying ``user_scopes`` or
``device_scopes`` itself; it calls one of the three functions below. That
single point is what keeps the enterprise hierarchy a governance boundary
rather than a suggestion.

The model, in one paragraph. An identity may hold bindings to subtrees of
``organizations → plants → areas``. A device becomes reachable to a bound
identity by being associated with one area. Resolving a binding therefore
means walking down the hierarchy to areas, then across ``device_scopes`` to
device ids. Three shapes of answer exist and are deliberately distinct:

* ``None`` — unrestricted. Two callers get it: an identity holding the ``*``
  wildcard (ADMIN by construction), and an identity with **no bindings at
  all**. The second is the migration-period default: every operator created
  before Phase 6.13-B has no bindings, and silently shrinking their reach to
  zero on upgrade would lock a working plant. Recorded here as a documented
  default, revisit-ready.
* a non-empty frozenset — the reachable device ids.
* the empty frozenset — bound, but nothing is reachable (for example a plant
  with no areas, or no devices assigned yet). This is a real answer, and it
  denies.

Denials are centralized too: :func:`ensure_device_in_scope` writes the
``SCOPE_DENIED`` audit row (with the acting identity) before raising, so a
blocked attempt leaves the same kind of evidence a refused permission does.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.security.audit import (
    ACTION_SCOPE_DENIED,
    PERMISSION_RESOURCE,
    STATUS_DENIED,
    record_security_event,
)
from app.security.org_models import Area, DeviceScope, Plant, ScopeLevel, UserScope
from app.security.rbac import WILDCARD, Principal

SCOPE_RESOURCE = "scope"

SCOPE_DENIED = ACTION_SCOPE_DENIED


async def resolve_device_scope(
    session: AsyncSession, principal: Principal
) -> frozenset[str] | None:
    """Return the device ids this identity may reach, or ``None`` for all.

    ``None`` is unrestricted reach: the wildcard principal, or an identity the
    scope system has never been told about. A returned frozenset is exhaustive:
    a device outside it, or one with no area assignment at all, is out of
    scope for this caller.
    """

    if WILDCARD in principal.permissions:
        return None
    bindings = list(
        await session.scalars(select(UserScope).where(UserScope.user_id == principal.user_id))
    )
    if not bindings:
        return None

    area_ids: set[UUID] = set()
    plant_ids: set[UUID] = set()
    organization_ids: set[UUID] = set()
    for binding in bindings:
        level = ScopeLevel(binding.scope_level)
        if level is ScopeLevel.AREA:
            area_ids.add(binding.scope_id)
        elif level is ScopeLevel.PLANT:
            plant_ids.add(binding.scope_id)
        else:
            organization_ids.add(binding.scope_id)

    if plant_ids:
        area_ids.update(await session.scalars(select(Area.id).where(Area.plant_id.in_(plant_ids))))
    if organization_ids:
        org_plant_ids = await session.scalars(
            select(Plant.id).where(Plant.organization_id.in_(organization_ids))
        )
        area_ids.update(
            await session.scalars(select(Area.id).where(Area.plant_id.in_(org_plant_ids)))
        )

    if not area_ids:
        return frozenset()
    return frozenset(
        await session.scalars(
            select(DeviceScope.device_id).where(DeviceScope.area_id.in_(area_ids))
        )
    )


async def ensure_device_in_scope(
    session: AsyncSession,
    principal: Principal,
    device_id: str,
    *,
    method: str | None = None,
    path: str | None = None,
) -> None:
    """Refuse the request unless ``device_id`` is inside the caller's scope.

    The check is a no-op for an unrestricted caller. For a constrained one,
    out-of-scope access is audited before the 403 is raised, because a blocked
    attempt is exactly the event an enterprise administrator needs to see.
    """

    scope = await resolve_device_scope(session, principal)
    if scope is None or device_id in scope:
        return
    details: dict[str, str] = {"device_id": device_id}
    if method is not None:
        details["method"] = method
    if path is not None:
        details["path"] = path
    await record_security_event(
        session,
        action=SCOPE_DENIED,
        resource=SCOPE_RESOURCE,
        resource_id=device_id,
        status=STATUS_DENIED,
        details=details,
        actor=principal.username,
        actor_user_id=principal.user_id,
    )
    raise AppError(
        SCOPE_DENIED,
        f"Device {device_id} is outside the scope assigned to this identity.",
        403,
        {"device_id": device_id},
    )


async def device_scope_filter(session: AsyncSession, principal: Principal) -> frozenset[str] | None:
    """Return the set of devices a constrained list may show, or ``None``.

    A convenience wrapper for read paths: ``None`` means "no filter", and any
    frozenset result is meant to be applied as a device-id membership filter.
    """

    return await resolve_device_scope(session, principal)


__all__ = [
    "PERMISSION_RESOURCE",
    "SCOPE_DENIED",
    "SCOPE_RESOURCE",
    "device_scope_filter",
    "ensure_device_in_scope",
    "resolve_device_scope",
]
