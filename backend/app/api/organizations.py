"""Enterprise organization API (Phase 6.13-B).

The hierarchy ``organizations → plants → areas`` is authored here; identities
are bound to subtrees here; devices are associated with areas here. Nothing in
this module invents a second device or asset system: a device scope row points
at the existing ``devices`` master record, and the association is removed as
soon as either side of it disappears.

Three permissions govern the whole surface, and the scope decisions they need
are made in :mod:`app.security.scope_policy`, never inline:

* ``org.read``    — see the hierarchy and any scope assignment.
* ``org.manage``  — author the structure itself.
* ``scope.manage`` — bind identities to subtrees and associate devices.

Every mutation is attributed to the authenticated caller: the actor name comes
from the principal and the ``actor_user_id`` lands on ``audit_events`` through
the request-scoped security context, exactly as on the migrated business
surface.

The router is declared without a prefix and mounted under both ``/api/v1`` and
``/api``, matching the platform convention.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.core.context import trace_id_context
from app.core.errors import AppError
from app.models import Device
from app.repositories.audit import AuditRepository
from app.security.dependencies import require_permission
from app.security.models import User
from app.security.org_models import Area, DeviceScope, Organization, Plant, ScopeLevel, UserScope
from app.security.rbac import ORG_MANAGE, ORG_READ, SCOPE_MANAGE, Principal
from app.security.repository import UserRepository

router = APIRouter(tags=["organization"])

Session = Annotated[AsyncSession, Depends(get_session)]


# --------------------------------------------------------------------------- #
# Contracts
# --------------------------------------------------------------------------- #


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str


class PlantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)


class PlantRead(OrganizationRead):
    organization_id: UUID


class AreaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)


class AreaRead(OrganizationRead):
    plant_id: UUID


class ScopeBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_level: ScopeLevel
    scope_id: UUID


class UserScopeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bindings: list[ScopeBinding] = Field(max_length=100)


class UserScopeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scope_level: ScopeLevel
    scope_id: UUID


class DeviceScopeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area_id: UUID | None = None


class DeviceScopeRead(BaseModel):
    device_id: str
    area_id: UUID | None


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

ReadOrg = Annotated[Principal, Depends(require_permission(ORG_READ))]


async def _require_organization(session: AsyncSession, organization_id: UUID) -> Organization:
    row = await session.get(Organization, organization_id)
    if row is None:
        raise AppError(
            "ORGANIZATION_NOT_FOUND", f"Organization {organization_id} was not found.", 404
        )
    return row


async def _require_plant(session: AsyncSession, plant_id: UUID) -> Plant:
    row = await session.get(Plant, plant_id)
    if row is None:
        raise AppError("PLANT_NOT_FOUND", f"Plant {plant_id} was not found.", 404)
    return row


async def _require_area(session: AsyncSession, area_id: UUID) -> Area:
    row = await session.get(Area, area_id)
    if row is None:
        raise AppError("AREA_NOT_FOUND", f"Area {area_id} was not found.", 404)
    return row


def _audit(
    session: AsyncSession,
    *,
    action: str,
    resource: str,
    resource_id: str,
    principal: Principal,
    details: dict[str, object] | None = None,
) -> None:
    """Record one mutation row attributed to the authenticated caller."""

    AuditRepository(session).add(
        trace_id=trace_id_context.get(),
        action=action,
        resource=resource,
        resource_id=resource_id,
        status="SUCCESS",
        actor=principal.username,
        actor_user_id=principal.user_id,
        details=details or {},
    )


# --------------------------------------------------------------------------- #
# Organizations
# --------------------------------------------------------------------------- #


@router.get("/organizations", response_model=list[OrganizationRead])
async def list_organizations(session: Session, principal: ReadOrg) -> list[OrganizationRead]:
    rows = list(await session.scalars(select(Organization).order_by(Organization.name)))
    return [OrganizationRead.model_validate(row) for row in rows]


@router.post("/organizations", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreate,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(ORG_MANAGE))],
) -> OrganizationRead:
    existing = await session.scalar(select(Organization).where(Organization.name == payload.name))
    if existing is not None:
        raise AppError("ORGANIZATION_EXISTS", f"Organization {payload.name!r} already exists.", 409)
    row = Organization(name=payload.name, description=payload.description)
    session.add(row)
    await session.flush()
    _audit(
        session,
        action="ORGANIZATION_CREATED",
        resource="organization",
        resource_id=str(row.id),
        principal=principal,
        details={"name": row.name},
    )
    await session.commit()
    return OrganizationRead.model_validate(row)


@router.get("/organizations/{organization_id}", response_model=OrganizationRead)
async def get_organization(
    organization_id: UUID, session: Session, principal: ReadOrg
) -> OrganizationRead:
    return OrganizationRead.model_validate(await _require_organization(session, organization_id))


@router.patch("/organizations/{organization_id}", response_model=OrganizationRead)
async def update_organization(
    organization_id: UUID,
    payload: OrganizationUpdate,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(ORG_MANAGE))],
) -> OrganizationRead:
    row = await _require_organization(session, organization_id)
    if payload.name is not None and payload.name != row.name:
        clash = await session.scalar(select(Organization).where(Organization.name == payload.name))
        if clash is not None:
            raise AppError(
                "ORGANIZATION_EXISTS", f"Organization {payload.name!r} already exists.", 409
            )
        row.name = payload.name
    if payload.description is not None:
        row.description = payload.description
    _audit(
        session,
        action="ORGANIZATION_UPDATED",
        resource="organization",
        resource_id=str(row.id),
        principal=principal,
    )
    await session.commit()
    return OrganizationRead.model_validate(row)


@router.delete("/organizations/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    organization_id: UUID,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(ORG_MANAGE))],
) -> None:
    row = await _require_organization(session, organization_id)
    _audit(
        session,
        action="ORGANIZATION_DELETED",
        resource="organization",
        resource_id=str(row.id),
        principal=principal,
        details={"name": row.name},
    )
    await session.delete(row)
    await session.commit()


# --------------------------------------------------------------------------- #
# Plants
# --------------------------------------------------------------------------- #


@router.get("/organizations/{organization_id}/plants", response_model=list[PlantRead])
async def list_plants(
    organization_id: UUID, session: Session, principal: ReadOrg
) -> list[PlantRead]:
    await _require_organization(session, organization_id)
    rows = list(
        await session.scalars(
            select(Plant).where(Plant.organization_id == organization_id).order_by(Plant.name)
        )
    )
    return [PlantRead.model_validate(row) for row in rows]


@router.post(
    "/organizations/{organization_id}/plants",
    response_model=PlantRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_plant(
    organization_id: UUID,
    payload: PlantCreate,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(ORG_MANAGE))],
) -> PlantRead:
    await _require_organization(session, organization_id)
    row = Plant(organization_id=organization_id, name=payload.name, description=payload.description)
    session.add(row)
    await session.flush()
    _audit(
        session,
        action="PLANT_CREATED",
        resource="plant",
        resource_id=str(row.id),
        principal=principal,
        details={"name": row.name, "organization_id": str(organization_id)},
    )
    await session.commit()
    return PlantRead.model_validate(row)


@router.patch("/plants/{plant_id}", response_model=PlantRead)
async def update_plant(
    plant_id: UUID,
    payload: PlantCreate,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(ORG_MANAGE))],
) -> PlantRead:
    row = await _require_plant(session, plant_id)
    row.name = payload.name
    row.description = payload.description
    _audit(
        session,
        action="PLANT_UPDATED",
        resource="plant",
        resource_id=str(row.id),
        principal=principal,
    )
    await session.commit()
    return PlantRead.model_validate(row)


@router.delete("/plants/{plant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plant(
    plant_id: UUID,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(ORG_MANAGE))],
) -> None:
    row = await _require_plant(session, plant_id)
    _audit(
        session,
        action="PLANT_DELETED",
        resource="plant",
        resource_id=str(row.id),
        principal=principal,
        details={"name": row.name},
    )
    await session.delete(row)
    await session.commit()


# --------------------------------------------------------------------------- #
# Areas
# --------------------------------------------------------------------------- #


@router.get("/plants/{plant_id}/areas", response_model=list[AreaRead])
async def list_areas(plant_id: UUID, session: Session, principal: ReadOrg) -> list[AreaRead]:
    await _require_plant(session, plant_id)
    rows = list(
        await session.scalars(select(Area).where(Area.plant_id == plant_id).order_by(Area.name))
    )
    return [AreaRead.model_validate(row) for row in rows]


@router.post(
    "/plants/{plant_id}/areas",
    response_model=AreaRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_area(
    plant_id: UUID,
    payload: AreaCreate,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(ORG_MANAGE))],
) -> AreaRead:
    await _require_plant(session, plant_id)
    row = Area(plant_id=plant_id, name=payload.name, description=payload.description)
    session.add(row)
    await session.flush()
    _audit(
        session,
        action="AREA_CREATED",
        resource="area",
        resource_id=str(row.id),
        principal=principal,
        details={"name": row.name, "plant_id": str(plant_id)},
    )
    await session.commit()
    return AreaRead.model_validate(row)


@router.patch("/areas/{area_id}", response_model=AreaRead)
async def update_area(
    area_id: UUID,
    payload: AreaCreate,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(ORG_MANAGE))],
) -> AreaRead:
    row = await _require_area(session, area_id)
    row.name = payload.name
    row.description = payload.description
    _audit(
        session,
        action="AREA_UPDATED",
        resource="area",
        resource_id=str(row.id),
        principal=principal,
    )
    await session.commit()
    return AreaRead.model_validate(row)


@router.delete("/areas/{area_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_area(
    area_id: UUID,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(ORG_MANAGE))],
) -> None:
    row = await _require_area(session, area_id)
    _audit(
        session,
        action="AREA_DELETED",
        resource="area",
        resource_id=str(row.id),
        principal=principal,
        details={"name": row.name},
    )
    await session.delete(row)
    await session.commit()


# --------------------------------------------------------------------------- #
# User scope bindings
# --------------------------------------------------------------------------- #


async def _validate_binding_target(session: AsyncSession, binding: ScopeBinding) -> None:
    """The (level, id) pair must name a real row; there is no polymorphic FK."""

    if binding.scope_level is ScopeLevel.ORGANIZATION:
        await _require_organization(session, binding.scope_id)
    elif binding.scope_level is ScopeLevel.PLANT:
        await _require_plant(session, binding.scope_id)
    else:
        await _require_area(session, binding.scope_id)


@router.get("/users/{user_id}/scopes", response_model=list[UserScopeRead])
async def list_user_scopes(
    user_id: UUID,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(SCOPE_MANAGE))],
) -> list[UserScopeRead]:
    if await session.get(User, user_id) is None:
        raise AppError("USER_NOT_FOUND", f"User {user_id} was not found.", 404)
    rows = list(await session.scalars(select(UserScope).where(UserScope.user_id == user_id)))
    return [UserScopeRead.model_validate(row) for row in rows]


@router.put("/users/{user_id}/scopes", response_model=list[UserScopeRead])
async def set_user_scopes(
    user_id: UUID,
    payload: UserScopeUpdate,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(SCOPE_MANAGE))],
) -> list[UserScopeRead]:
    """Replace the identity's bindings wholesale.

    A full replacement, rather than a patch, is what makes the call idempotent
    and the resulting reach describable from one request body alone.
    """

    user = await UserRepository(session).get(user_id)
    if user is None:
        raise AppError("USER_NOT_FOUND", f"User {user_id} was not found.", 404)
    for binding in payload.bindings:
        await _validate_binding_target(session, binding)

    await session.execute(delete(UserScope).where(UserScope.user_id == user_id))
    for binding in payload.bindings:
        session.add(
            UserScope(
                user_id=user_id, scope_level=binding.scope_level.value, scope_id=binding.scope_id
            )
        )
    _audit(
        session,
        action="USER_SCOPE_ASSIGNED",
        resource="user",
        resource_id=str(user_id),
        principal=principal,
        details={
            "bindings": [
                {"scope_level": b.scope_level.value, "scope_id": str(b.scope_id)}
                for b in payload.bindings
            ]
        },
    )
    await session.commit()
    rows = list(await session.scalars(select(UserScope).where(UserScope.user_id == user_id)))
    return [UserScopeRead.model_validate(row) for row in rows]


# --------------------------------------------------------------------------- #
# Device scope association
# --------------------------------------------------------------------------- #


@router.get("/devices/{device_id}/scope", response_model=DeviceScopeRead)
async def get_device_scope(
    device_id: str,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(SCOPE_MANAGE))],
) -> DeviceScopeRead:
    row = await session.get(DeviceScope, device_id)
    return DeviceScopeRead(device_id=device_id, area_id=row.area_id if row else None)


@router.put("/devices/{device_id}/scope", response_model=DeviceScopeRead)
async def set_device_scope(
    device_id: str,
    payload: DeviceScopeUpdate,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(SCOPE_MANAGE))],
) -> DeviceScopeRead:
    """Associate the device master record with an area, or clear the row.

    The device must exist in ``devices``; the hierarchy owns location, the
    device master owns identity, and this row is the only bridge between them.
    """

    if await session.scalar(select(Device.id).where(Device.device_id == device_id)) is None:
        raise AppError("DEVICE_NOT_FOUND", f"Device {device_id} was not found.", 404)
    if payload.area_id is not None:
        await _require_area(session, payload.area_id)

    row = await session.get(DeviceScope, device_id)
    if payload.area_id is None:
        if row is not None:
            await session.delete(row)
    else:
        if row is None:
            row = DeviceScope(device_id=device_id, area_id=payload.area_id)
            session.add(row)
        else:
            row.area_id = payload.area_id
    _audit(
        session,
        action="DEVICE_SCOPE_ASSIGNED",
        resource="device",
        resource_id=device_id,
        principal=principal,
        details={"area_id": str(payload.area_id) if payload.area_id else None},
    )
    await session.commit()
    return DeviceScopeRead(device_id=device_id, area_id=payload.area_id)
