"""Scope-aware authorization (Phase 6.13-B, hardened in Phase 6.13-D).

Every scope decision in the platform is made here. A route never answers "may
this caller touch this device?" by querying ``user_scopes`` or
``device_scopes`` itself; it calls one of the functions below. That single
point is what keeps the enterprise hierarchy a governance boundary rather than
a suggestion.

Phase 6.13-D replaces the migration-period default with an explicit policy
mode. The model, in one paragraph. An identity may hold bindings to subtrees
of ``organizations → plants → areas``. A device becomes reachable to a bound
identity by being associated with one area. Resolving a binding therefore
means walking down the hierarchy to areas, then across ``device_scopes`` to
device ids. :class:`ScopeAccessMode` names the three shapes of answer, and
they are deliberately distinct:

* ``UNRESTRICTED`` — every device, granted by exactly one thing: the ``*``
  wildcard held through real RBAC grants. Nothing else yields it. In
  particular, an identity with **no bindings** no longer falls through to
  global reach; that implicit default is gone.
* ``SCOPED`` — a non-empty (or empty) frozenset of the reachable device ids.
  The empty frozenset is a real answer, and it denies: a plant with no areas,
  or no devices assigned yet, grants nothing.
* ``DENIED`` — the identity has no scope bindings at all. Scoped-resource
  access is refused with ``403 SCOPE_DENIED`` (Phase 6.13-D deny-by-default).
  Operators are provisioned by binding them, or by granting the wildcard
  through a role; an unbound operator has no reach by construction.

The migration-compatibility concern this replaces is handled out of band:
``scripts/check_scope_readiness.py`` lists every ACTIVE non-admin identity
without bindings so an operator can provision them before deploying this
phase, instead of the platform silently granting them the world.

Denials are centralized too: :func:`ensure_device_in_scope` and
:func:`ensure_organization_visible` write the ``SCOPE_DENIED`` audit row (with
the acting identity) before raising, so a blocked attempt leaves the same kind
of evidence a refused permission does.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.platform_observability.metrics import security_scope_denied_total
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

ORG_RESOURCE = "organization"
PLANT_RESOURCE = "plant"
AREA_RESOURCE = "area"


class ScopeAccessMode(StrEnum):
    """The explicit answer shapes of the scope system.

    ``None`` no longer carries three meanings at once. A caller that receives
    :attr:`UNRESTRICTED` got it from a real wildcard grant; a caller that
    receives :attr:`DENIED` has no bindings; anything else is an explicit set.
    """

    UNRESTRICTED = "UNRESTRICTED"
    SCOPED = "SCOPED"
    DENIED = "DENIED"


@dataclass(frozen=True, slots=True)
class DeviceScopeAccess:
    """One resolved device-scope answer.

    ``device_ids`` is ``None`` only when ``mode`` is ``UNRESTRICTED``; a
    ``SCOPED`` answer always carries a frozenset, and ``DENIED`` carries the
    empty frozenset so a forgotten mode check fails closed.
    """

    mode: ScopeAccessMode
    device_ids: frozenset[str] | None

    def allows(self, device_id: str) -> bool:
        """Return whether this answer admits ``device_id``."""

        if self.mode is ScopeAccessMode.UNRESTRICTED:
            return True
        if self.mode is ScopeAccessMode.SCOPED and self.device_ids is not None:
            return device_id in self.device_ids
        return False


@dataclass(frozen=True, slots=True)
class OrganizationScopeAccess:
    """One resolved organization-read answer.

    When ``mode`` is ``UNRESTRICTED`` the id sets are empty and mean "no
    filter". For ``SCOPED`` and ``DENIED`` the sets are exhaustive: they name
    exactly the hierarchy rows the caller may see, including the ancestors of
    each bound subtree (a caller bound to one area still needs to see the
    plant and organization that contain it) and the descendants of each bound
    node (binding an organization means seeing everything inside it).
    """

    mode: ScopeAccessMode
    organization_ids: frozenset[UUID]
    plant_ids: frozenset[UUID]
    area_ids: frozenset[UUID]

    def shows_organization(self, organization_id: UUID) -> bool:
        if self.mode is ScopeAccessMode.UNRESTRICTED:
            return True
        return organization_id in self.organization_ids

    def shows_plant(self, plant_id: UUID) -> bool:
        if self.mode is ScopeAccessMode.UNRESTRICTED:
            return True
        return plant_id in self.plant_ids

    def shows_area(self, area_id: UUID) -> bool:
        if self.mode is ScopeAccessMode.UNRESTRICTED:
            return True
        return area_id in self.area_ids


async def resolve_device_access(session: AsyncSession, principal: Principal) -> DeviceScopeAccess:
    """Resolve the caller's device reach into an explicit answer.

    ``UNRESTRICTED`` comes only from the RBAC wildcard. Bindings, when present,
    resolve to the exhaustive set of reachable device ids. No bindings at all
    is ``DENIED``: the Phase 6.13-D deny-by-default mode. A device with no
    area assignment is outside every scoped caller's reach.
    """

    if WILDCARD in principal.permissions:
        return DeviceScopeAccess(mode=ScopeAccessMode.UNRESTRICTED, device_ids=None)
    bindings = list(
        await session.scalars(select(UserScope).where(UserScope.user_id == principal.user_id))
    )
    if not bindings:
        return DeviceScopeAccess(mode=ScopeAccessMode.DENIED, device_ids=frozenset())

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
        return DeviceScopeAccess(mode=ScopeAccessMode.SCOPED, device_ids=frozenset())
    device_ids = frozenset(
        await session.scalars(
            select(DeviceScope.device_id).where(DeviceScope.area_id.in_(area_ids))
        )
    )
    return DeviceScopeAccess(mode=ScopeAccessMode.SCOPED, device_ids=device_ids)


async def resolve_organization_access(
    session: AsyncSession, principal: Principal
) -> OrganizationScopeAccess:
    """Resolve which hierarchy rows the caller may see on read paths.

    The wildcard sees everything. A bound caller sees its bound subtrees plus
    their ancestors and descendants, as described on
    :class:`OrganizationScopeAccess`. No bindings at all is ``DENIED``: the
    hierarchy itself becomes invisible rather than globally readable, because
    "org.read" granted to every role was written when scope did not exist.
    """

    if WILDCARD in principal.permissions:
        return OrganizationScopeAccess(
            mode=ScopeAccessMode.UNRESTRICTED,
            organization_ids=frozenset(),
            plant_ids=frozenset(),
            area_ids=frozenset(),
        )
    bindings = list(
        await session.scalars(select(UserScope).where(UserScope.user_id == principal.user_id))
    )
    if not bindings:
        return OrganizationScopeAccess(
            mode=ScopeAccessMode.DENIED,
            organization_ids=frozenset(),
            plant_ids=frozenset(),
            area_ids=frozenset(),
        )

    area_ids: set[UUID] = set()
    plant_ids: set[UUID] = set()
    organization_ids: set[UUID] = set()
    for binding in bindings:
        level = ScopeLevel(binding.scope_level)
        if level is ScopeLevel.ORGANIZATION:
            organization_ids.add(binding.scope_id)
        elif level is ScopeLevel.PLANT:
            plant_ids.add(binding.scope_id)
        else:
            area_ids.add(binding.scope_id)

    # Ancestors of every bound node, so the caller can navigate to its scope.
    # Areas resolve first, then plants: an area binding reaches its
    # organization only through the plant row the area hangs from, so the
    # plant pass must run after the area pass has collected those plants.
    if area_ids:
        ancestor_areas = await session.execute(
            select(Area.id, Area.plant_id).where(Area.id.in_(area_ids))
        )
        for area_id, plant_id in ancestor_areas.all():
            area_ids.add(area_id)
            plant_ids.add(plant_id)
    if plant_ids:
        ancestor_plants = await session.execute(
            select(Plant.id, Plant.organization_id).where(Plant.id.in_(plant_ids))
        )
        for plant_id, organization_id in ancestor_plants.all():
            plant_ids.add(plant_id)
            organization_ids.add(organization_id)

    # Descendants of every bound node, because binding a subtree means seeing
    # everything inside it.
    if organization_ids:
        org_plants = await session.scalars(
            select(Plant.id).where(Plant.organization_id.in_(organization_ids))
        )
        plant_ids.update(org_plants)
    if plant_ids:
        plant_areas = await session.scalars(select(Area.id).where(Area.plant_id.in_(plant_ids)))
        area_ids.update(plant_areas)

    return OrganizationScopeAccess(
        mode=ScopeAccessMode.SCOPED,
        organization_ids=frozenset(organization_ids),
        plant_ids=frozenset(plant_ids),
        area_ids=frozenset(area_ids),
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

    Out-of-scope access is audited before the 403 is raised, because a blocked
    attempt is exactly the event an enterprise administrator needs to see.
    ``DENIED`` mode denies every device, including unassigned ones.
    """

    access = await resolve_device_access(session, principal)
    if access.allows(device_id):
        return
    security_scope_denied_total.inc()
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


async def ensure_organization_visible(
    session: AsyncSession,
    principal: Principal,
    resource: str,
    resource_id: UUID | str,
    access: OrganizationScopeAccess,
    *,
    method: str | None = None,
    path: str | None = None,
) -> None:
    """Refuse an organization-tree read the caller's scope does not cover.

    ``resource`` is one of ``organization`` / ``plant`` / ``area``; the caller
    passes the already-resolved :class:`OrganizationScopeAccess` so a route
    listing several rows filters them itself and only single-row lookups pay
    for the audit-and-raise path here.
    """

    visible: bool
    if resource == ORG_RESOURCE:
        visible = access.shows_organization(UUID(str(resource_id)))
    elif resource == PLANT_RESOURCE:
        visible = access.shows_plant(UUID(str(resource_id)))
    elif resource == AREA_RESOURCE:
        visible = access.shows_area(UUID(str(resource_id)))
    else:  # pragma: no cover - defensive: the resource vocabulary is closed
        visible = False
    if visible:
        return
    security_scope_denied_total.inc()
    details: dict[str, str] = {"resource": resource, "resource_id": str(resource_id)}
    if method is not None:
        details["method"] = method
    if path is not None:
        details["path"] = path
    await record_security_event(
        session,
        action=SCOPE_DENIED,
        resource=resource,
        resource_id=str(resource_id),
        status=STATUS_DENIED,
        details=details,
        actor=principal.username,
        actor_user_id=principal.user_id,
    )
    raise AppError(
        SCOPE_DENIED,
        f"The {resource} is outside the scope assigned to this identity.",
        403,
        {"resource": resource, "resource_id": str(resource_id)},
    )


async def device_scope_filter(session: AsyncSession, principal: Principal) -> frozenset[str] | None:
    """Return the set of devices a constrained list may show, or ``None``.

    ``None`` now means exactly one thing: the caller holds the wildcard and no
    filter may be applied. ``SCOPED`` and ``DENIED`` both return a frozenset
    (the latter empty), so a read path that applies the filter as a membership
    test fails closed even if it never inspects the mode.
    """

    access = await resolve_device_access(session, principal)
    if access.mode is ScopeAccessMode.UNRESTRICTED:
        return None
    return access.device_ids if access.device_ids is not None else frozenset()


__all__ = [
    "AREA_RESOURCE",
    "DeviceScopeAccess",
    "ORG_RESOURCE",
    "OrganizationScopeAccess",
    "PERMISSION_RESOURCE",
    "PLANT_RESOURCE",
    "SCOPE_DENIED",
    "SCOPE_RESOURCE",
    "ScopeAccessMode",
    "device_scope_filter",
    "ensure_device_in_scope",
    "ensure_organization_visible",
    "resolve_device_access",
    "resolve_organization_access",
]
