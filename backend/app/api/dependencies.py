"""FastAPI dependencies."""

from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import Database
from app.websocket.manager import WebSocketManager


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.database
    async for session in database.session():
        yield session


def get_redis(request: Request) -> Redis:
    return cast(Redis, request.app.state.redis)


def get_websocket_manager(request: Request) -> WebSocketManager:
    return cast(WebSocketManager, request.app.state.websocket_manager)
