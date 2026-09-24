"""Versioned device configuration endpoints.

Lifecycle exposed here::

    create draft -> get/update draft -> validate -> publish -> apply status
                                            |
                                            +-> clone / rollback creates a new draft

Published and archived versions are read-only. A change is always a new version, so
the version sequence is strictly increasing and history is never rewritten.

Publishing records the desired version in the database and then asks the gateway to
apply it. The response reports both, so a failed application is visible instead of
being presented as success.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_configuration_applier, get_session
from app.assetconfig.apply import DefinitionApplier
from app.assetconfig.contracts import (
    AuditEventRead,
    ConfigurationDetailRead,
    ConfigurationStatusRead,
    ConfigurationSummaryRead,
    PublishResultRead,
    ValidationResultRead,
)
from app.assetconfig.service import ConfigurationService
from app.security.dependencies import require_permission
from app.security.rbac import CONFIG_PUBLISH, CONFIG_READ, CONFIG_WRITE, Principal
from app.security.scope_policy import ensure_device_in_scope

router = APIRouter(tags=["configuration"])

Applier = Annotated[DefinitionApplier, Depends(get_configuration_applier)]

#: Every route below declares its own permission. The dependency returns the
#: authenticated principal, so draft and publish operations record the real
#: identity as the actor instead of a caller-supplied header.
ReadConfiguration = Annotated[Principal, Depends(require_permission(CONFIG_READ))]


def _service(session: AsyncSession, applier: DefinitionApplier) -> ConfigurationService:
    return ConfigurationService(session, applier)


@router.get(
    "/devices/{device_id}/configurations",
    response_model=list[ConfigurationSummaryRead],
)
async def list_configurations(
    device_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    applier: Applier,
    principal: ReadConfiguration,
) -> list[ConfigurationSummaryRead]:
    await ensure_device_in_scope(session, principal, device_id)
    rows = await _service(session, applier).list_configurations(device_id)
    return [ConfigurationSummaryRead.model_validate(row) for row in rows]


@router.post(
    "/devices/{device_id}/configurations",
    response_model=ConfigurationDetailRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_configuration(
    device_id: str,
    payload: Annotated[dict[str, Any], Body()],
    session: Annotated[AsyncSession, Depends(get_session)],
    applier: Applier,
    principal: Annotated[Principal, Depends(require_permission(CONFIG_WRITE))],
) -> ConfigurationDetailRead:
    await ensure_device_in_scope(session, principal, device_id)
    row = await _service(session, applier).create_draft(device_id, payload, principal.username)
    return ConfigurationDetailRead.model_validate(row)


@router.get(
    "/devices/{device_id}/configurations/{version}",
    response_model=ConfigurationDetailRead,
)
async def get_configuration(
    device_id: str,
    version: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    applier: Applier,
    principal: ReadConfiguration,
) -> ConfigurationDetailRead:
    await ensure_device_in_scope(session, principal, device_id)
    row = await _service(session, applier).get_configuration(device_id, version)
    return ConfigurationDetailRead.model_validate(row)


@router.patch(
    "/devices/{device_id}/configurations/{version}",
    response_model=ConfigurationDetailRead,
)
async def update_configuration(
    device_id: str,
    version: int,
    payload: Annotated[dict[str, Any], Body()],
    session: Annotated[AsyncSession, Depends(get_session)],
    applier: Applier,
    principal: Annotated[Principal, Depends(require_permission(CONFIG_WRITE))],
) -> ConfigurationDetailRead:
    await ensure_device_in_scope(session, principal, device_id)
    row = await _service(session, applier).update_draft(
        device_id, version, payload, principal.username
    )
    return ConfigurationDetailRead.model_validate(row)


@router.delete(
    "/devices/{device_id}/configurations/{version}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_configuration(
    device_id: str,
    version: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    applier: Applier,
    principal: Annotated[Principal, Depends(require_permission(CONFIG_WRITE))],
) -> None:
    await ensure_device_in_scope(session, principal, device_id)
    await _service(session, applier).delete_draft(device_id, version)


@router.post(
    "/devices/{device_id}/configurations/{version}/validate",
    response_model=ValidationResultRead,
)
async def validate_configuration(
    device_id: str,
    version: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    applier: Applier,
    principal: Annotated[Principal, Depends(require_permission(CONFIG_WRITE))],
) -> ValidationResultRead:
    await ensure_device_in_scope(session, principal, device_id)
    result = await _service(session, applier).validate_version(device_id, version)
    return ValidationResultRead.model_validate(result)


@router.post(
    "/devices/{device_id}/configurations/{version}/clone",
    response_model=ConfigurationDetailRead,
    status_code=status.HTTP_201_CREATED,
)
async def clone_configuration(
    device_id: str,
    version: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    applier: Applier,
    principal: Annotated[Principal, Depends(require_permission(CONFIG_WRITE))],
) -> ConfigurationDetailRead:
    await ensure_device_in_scope(session, principal, device_id)
    row = await _service(session, applier).clone_version(device_id, version, principal.username)
    return ConfigurationDetailRead.model_validate(row)


@router.post(
    "/devices/{device_id}/configurations/{version}/publish",
    response_model=PublishResultRead,
)
async def publish_configuration(
    device_id: str,
    version: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    applier: Applier,
    principal: Annotated[Principal, Depends(require_permission(CONFIG_PUBLISH))],
) -> PublishResultRead:
    await ensure_device_in_scope(session, principal, device_id)
    row, status_row = await _service(session, applier).publish(
        device_id, version, principal.username
    )
    return PublishResultRead(
        configuration=ConfigurationDetailRead.model_validate(row),
        status=ConfigurationStatusRead.model_validate(status_row),
    )


@router.get(
    "/devices/{device_id}/configuration-status",
    response_model=ConfigurationStatusRead,
)
async def configuration_status(
    device_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    applier: Applier,
    principal: ReadConfiguration,
) -> ConfigurationStatusRead:
    await ensure_device_in_scope(session, principal, device_id)
    return ConfigurationStatusRead.model_validate(
        await _service(session, applier).status(device_id)
    )


@router.post(
    "/devices/{device_id}/configuration-status/apply",
    response_model=ConfigurationStatusRead,
)
async def apply_configuration(
    device_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    applier: Applier,
    principal: Annotated[Principal, Depends(require_permission(CONFIG_PUBLISH))],
) -> ConfigurationStatusRead:
    await ensure_device_in_scope(session, principal, device_id)
    """Retry applying the currently published version."""

    return ConfigurationStatusRead.model_validate(
        await _service(session, applier).apply_current(device_id, principal.username)
    )


@router.get(
    "/devices/{device_id}/configuration-audit",
    response_model=list[AuditEventRead],
)
async def configuration_audit(
    device_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    applier: Applier,
    principal: ReadConfiguration,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditEventRead]:
    await ensure_device_in_scope(session, principal, device_id)
    rows = await _service(session, applier).audit_history(device_id, limit)
    return [AuditEventRead.model_validate(row) for row in rows]
