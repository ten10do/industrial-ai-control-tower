"""Phase 6.7 connectivity APIs.

Exposes the gateway device inventory, per-device lifecycle status, and aggregate
ingestion totals, plus local start/stop control over the gateway's own polling
runtime. No endpoint here writes to a device: start and stop only toggle whether the
gateway polls, so nothing in this module can command plant equipment.

Phase 6.13-A gates the surface: reads require ``connectivity.read``, and the
polling controls require ``connectivity.control``.

The router is declared without a prefix and mounted twice by the application as
``/api/v1/connectivity`` (the repository-wide API contract namespace) and
``/api/connectivity`` (the shorthand used by the Phase 6.7 specification).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.core.errors import AppError
from app.gateway import (
    ConnectivitySummary,
    DeviceStatusRead,
    GatewayConfigurationError,
    IndustrialProtocolGateway,
)
from app.security.dependencies import require_permission
from app.security.rbac import CONNECTIVITY_CONTROL, CONNECTIVITY_READ, Principal
from app.security.scope_policy import ensure_device_in_scope

router = APIRouter(tags=["connectivity"])

ReadConnectivity = Annotated[Principal, Depends(require_permission(CONNECTIVITY_READ))]

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_gateway(request: Request) -> IndustrialProtocolGateway | None:
    """Return the process gateway, or ``None`` when connectivity is not enabled."""

    return getattr(request.app.state, "gateway", None)


GatewayDep = Annotated[IndustrialProtocolGateway | None, Depends(get_gateway)]


def _require(gateway: IndustrialProtocolGateway | None) -> IndustrialProtocolGateway:
    if gateway is None:
        raise AppError(
            "CONNECTIVITY_DISABLED",
            "The industrial protocol gateway is not enabled in this deployment.",
            503,
        )
    return gateway


def _device_not_found(exc: GatewayConfigurationError) -> AppError:
    return AppError("CONNECTIVITY_DEVICE_NOT_FOUND", str(exc), 404)


@router.get("/connectivity/summary", response_model=ConnectivitySummary)
async def connectivity_summary(
    request: Request, gateway: GatewayDep, principal: ReadConnectivity
) -> ConnectivitySummary:
    """Return gateway availability and aggregate device state."""

    if gateway is None:
        return ConnectivitySummary(
            gateway_enabled=bool(getattr(request.app.state, "gateway_enabled", False)),
            gateway_available=False,
            gateway_error=getattr(request.app.state, "gateway_error", None),
        )
    return gateway.summary()


@router.get("/connectivity/devices", response_model=list[DeviceStatusRead])
async def list_connectivity_devices(
    gateway: GatewayDep, principal: ReadConnectivity
) -> list[DeviceStatusRead]:
    """Return every configured device and its current lifecycle state."""

    if gateway is None:
        return []
    return gateway.statuses()


@router.get("/connectivity/devices/{device_id}", response_model=DeviceStatusRead)
async def get_connectivity_device(
    device_id: str, gateway: GatewayDep, principal: ReadConnectivity, session: SessionDep
) -> DeviceStatusRead:
    """Return one device's lifecycle status."""

    await ensure_device_in_scope(session, principal, device_id)
    try:
        return _require(gateway).status(device_id)
    except GatewayConfigurationError as exc:
        raise _device_not_found(exc) from exc


@router.post("/connectivity/devices/{device_id}/start", response_model=DeviceStatusRead)
async def start_connectivity_device(
    device_id: str,
    gateway: GatewayDep,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require_permission(CONNECTIVITY_CONTROL))],
) -> DeviceStatusRead:
    """Start polling for one device."""

    await ensure_device_in_scope(session, principal, device_id)
    try:
        return await _require(gateway).start_device(device_id)
    except GatewayConfigurationError as exc:
        raise _device_not_found(exc) from exc


@router.post("/connectivity/devices/{device_id}/stop", response_model=DeviceStatusRead)
async def stop_connectivity_device(
    device_id: str,
    gateway: GatewayDep,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require_permission(CONNECTIVITY_CONTROL))],
) -> DeviceStatusRead:
    """Stop polling for one device."""

    await ensure_device_in_scope(session, principal, device_id)
    try:
        return await _require(gateway).stop_device(device_id)
    except GatewayConfigurationError as exc:
        raise _device_not_found(exc) from exc
