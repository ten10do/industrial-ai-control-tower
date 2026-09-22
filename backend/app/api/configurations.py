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

from app.api.dependencies import get_actor, get_configuration_applier, get_session
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

router = APIRouter(tags=["configuration"])

Actor = Annotated[str, Depends(get_actor)]
Applier = Annotated[DefinitionApplier, Depends(get_configuration_applier)]


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
) -> list[ConfigurationSummaryRead]:
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
    actor: Actor,
) -> ConfigurationDetailRead:
    row = await _service(session, applier).create_draft(device_id, payload, actor)
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
) -> ConfigurationDetailRead:
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
    actor: Actor,
) -> ConfigurationDetailRead:
    row = await _service(session, applier).update_draft(device_id, version, payload, actor)
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
) -> None:
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
) -> ValidationResultRead:
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
    actor: Actor,
) -> ConfigurationDetailRead:
    row = await _service(session, applier).clone_version(device_id, version, actor)
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
    actor: Actor,
) -> PublishResultRead:
    row, status_row = await _service(session, applier).publish(device_id, version, actor)
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
) -> ConfigurationStatusRead:
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
    actor: Actor,
) -> ConfigurationStatusRead:
    """Retry applying the currently published version."""

    return ConfigurationStatusRead.model_validate(
        await _service(session, applier).apply_current(device_id, actor)
    )


@router.get(
    "/devices/{device_id}/configuration-audit",
    response_model=list[AuditEventRead],
)
async def configuration_audit(
    device_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    applier: Applier,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditEventRead]:
    rows = await _service(session, applier).audit_history(device_id, limit)
    return [AuditEventRead.model_validate(row) for row in rows]
