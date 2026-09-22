"""Resolve the authoritative device definition for every device.

Two sources exist and their precedence is fixed, not ad hoc:

1. A published ``device_configurations`` row is authoritative. When one exists,
   the YAML file is never consulted for that device.
2. The Phase 6.7 YAML file remains a bootstrap for devices with no published
   configuration, and it stays available for documentation, local bootstrap, and
   tests. It is never a second opinion that can contradict a published version.

There is no mode in which a device is read sometimes from YAML and sometimes from
the database with the same precedence, so "which configuration is live" has one
answer per device at any moment.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assetconfig.models import ConfigurationSource
from app.assetconfig.repository import ConfigurationRepository
from app.gateway.config import load_gateway_config
from app.gateway.errors import GatewayConfigurationError
from app.gateway.models import DeviceDefinition


@dataclass(frozen=True, slots=True)
class ResolvedDefinition:
    """One device's effective definition plus where it came from."""

    device_id: str
    definition: DeviceDefinition
    version: int | None
    source: ConfigurationSource


async def published_definitions(
    session: AsyncSession,
) -> list[ResolvedDefinition]:
    """Read every published configuration, newest authority first."""

    rows = await ConfigurationRepository(session).list_published()
    resolved: list[ResolvedDefinition] = []
    for row in rows:
        resolved.append(
            ResolvedDefinition(
                device_id=row.device_id,
                definition=DeviceDefinition.model_validate(row.configuration),
                version=row.version,
                source=ConfigurationSource.DATABASE,
            )
        )
    return resolved


def bootstrap_definitions(path: Path) -> list[ResolvedDefinition]:
    """Read the YAML bootstrap file, tolerating its absence."""

    if not path.exists():
        return []
    definitions = load_gateway_config(path)
    return [
        ResolvedDefinition(
            device_id=definition.device_id,
            definition=definition,
            version=None,
            source=ConfigurationSource.BOOTSTRAP,
        )
        for definition in definitions
    ]


async def resolve_definitions(
    *,
    sessions: async_sessionmaker[AsyncSession],
    yaml_path: Path,
    managed: bool,
    on_error: Callable[[str], None] | None = None,
) -> list[ResolvedDefinition]:
    """Resolve the effective definition of every device.

    ``managed=False`` reproduces the Phase 6.7 behaviour exactly: the YAML file is
    the only source. ``managed=True`` makes published database configurations
    authoritative and uses YAML only for devices that have none.
    """

    if not managed:
        return bootstrap_definitions(yaml_path)

    resolved: list[ResolvedDefinition] = []
    try:
        async with sessions() as session:
            resolved = await published_definitions(session)
    except Exception as exc:  # a database problem must not fabricate definitions
        if on_error is not None:
            on_error(f"published configuration could not be read: {exc}")
        resolved = []
    managed_ids = {item.device_id for item in resolved}
    try:
        bootstrap = bootstrap_definitions(yaml_path)
    except GatewayConfigurationError as exc:
        if on_error is not None:
            on_error(str(exc))
        bootstrap = []
    resolved.extend(item for item in bootstrap if item.device_id not in managed_ids)
    return resolved
