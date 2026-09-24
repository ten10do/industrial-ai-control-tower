"""FastAPI dependencies."""

import re
from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.assetconfig.apply import DefinitionApplier, UnavailableApplier
from app.core.errors import AppError
from app.infrastructure.database.session import Database
from app.websocket.manager import WebSocketManager

_ACTOR_PATTERN = re.compile(r"[A-Za-z0-9._@-]{1,200}")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.database
    async for session in database.session():
        yield session


def get_redis(request: Request) -> Redis:
    return cast(Redis, request.app.state.redis)


def get_websocket_manager(request: Request) -> WebSocketManager:
    return cast(WebSocketManager, request.app.state.websocket_manager)


def get_actor(request: Request) -> str:
    """Return the caller-supplied actor label, defaulting to ``system``.

    Legacy metadata only. Phase 6.13-A migrated the last business mutations
    (alarms, alarm rules, asset configuration, connectivity) to the
    authenticated identity, so no governed route consumes this dependency any
    more: every business mutation attributes its actor to the authenticated
    user through :mod:`app.security.dependencies`.

    The header is not deleted. Clients that still send ``X-Actor`` keep working,
    and the raw value travels in the request-scoped security context as
    ``legacy_actor``, where the audit writer records it as
    ``details["legacy_x_actor"]`` next to the identity that actually acted. It
    grants no authority and is never validated for shape there: a forged label
    is recorded as the claim it is.
    """

    raw = request.headers.get("X-Actor", "").strip()
    if not raw:
        return "system"
    if not _ACTOR_PATTERN.fullmatch(raw):
        raise AppError(
            "INVALID_ACTOR",
            "The X-Actor header may only contain letters, digits, dot, underscore, "
            "hyphen, or at-sign, up to 200 characters.",
            422,
        )
    return raw


def get_configuration_applier(request: Request) -> DefinitionApplier:
    """Return the runtime applier owned by this process."""

    return cast(
        DefinitionApplier,
        getattr(request.app.state, "configuration_applier", UnavailableApplier()),
    )
