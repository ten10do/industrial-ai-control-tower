"""Login brute-force protection.

Scope is deliberately one endpoint. A general rate-limiting gateway belongs to
an edge proxy, not to this application, and pretending otherwise would produce
a limiter that is trivially bypassed by adding a second instance. What this
does cover is the one thing an application alone can defend: repeated failed
authentication against ``POST /auth/login`` from the same origin.

The counter lives in Redis so it is shared across processes. When Redis is
unreachable the limiter fails *open* and logs, because the alternative is
locking every operator out of a working platform because a cache is down. The
failure mode is recorded in the security documentation as a known limitation
rather than hidden.
"""

from __future__ import annotations

import logging
from typing import Protocol, cast

from fastapi import Request
from redis.asyncio import Redis

from app.security.errors import LoginRateLimitedError

logger = logging.getLogger(__name__)

KEY_PREFIX = "security:login:fail:"


class CounterStore(Protocol):
    """The four Redis operations the limiter needs.

    ``get`` returns ``bytes`` from a raw Redis client and ``str`` from a
    decoding one, so the union is the honest signature; the limiter parses
    either. Only these four commands are used, which is what keeps the test
    double small enough to stay obviously correct.
    """

    async def get(self, name: str) -> bytes | str | None: ...

    async def incr(self, name: str, amount: int = 1) -> int: ...

    async def expire(self, name: str, time: int) -> bool: ...

    async def delete(self, *names: str) -> int: ...


def client_ip(request: Request) -> str:
    """Return the source address used for rate limiting and audit.

    Only the socket peer is used. ``X-Forwarded-For`` is client-controlled, and
    trusting it without a configured trusted-proxy boundary would let an
    attacker pick their own bucket, or forge the address written into the audit
    trail. Proxy-aware resolution is a deployment concern, not a foundation one.
    """

    return request.client.host if request.client is not None else "unknown"


class LoginRateLimiter:
    """Count failed logins per origin within a rolling window."""

    def __init__(
        self,
        store: CounterStore | None,
        *,
        limit: int = 5,
        window_seconds: int = 60,
    ) -> None:
        self.store = store
        self.limit = limit
        self.window_seconds = window_seconds

    @classmethod
    def from_redis(
        cls, redis: Redis | None, *, limit: int, window_seconds: int
    ) -> LoginRateLimiter:
        return cls(
            cast(CounterStore, redis) if redis is not None else None,
            limit=limit,
            window_seconds=window_seconds,
        )

    def _key(self, identity: str) -> str:
        return f"{KEY_PREFIX}{identity}"

    async def failure_count(self, identity: str) -> int:
        if self.store is None:
            return 0
        try:
            raw = await self.store.get(self._key(identity))
        except Exception:  # pragma: no cover - defensive: Redis is optional
            logger.warning("login_rate_limit_unavailable", exc_info=True)
            return 0
        if raw is None:
            return 0
        text = raw.decode("ascii", "replace") if isinstance(raw, bytes) else raw
        try:
            return int(text)
        except ValueError:
            return 0

    async def check(self, identity: str) -> None:
        """Raise :class:`LoginRateLimitedError` when the origin is already blocked."""

        count = await self.failure_count(identity)
        if count >= self.limit:
            raise LoginRateLimitedError(self.window_seconds)

    async def register_failure(self, identity: str) -> int:
        """Count one failure and (re)arm the window. Returns the new count."""

        if self.store is None:
            return 0
        try:
            key = self._key(identity)
            count = int(await self.store.incr(key, 1))
            if count == 1:
                await self.store.expire(key, self.window_seconds)
            return count
        except Exception:  # pragma: no cover - defensive: Redis is optional
            logger.warning("login_rate_limit_unavailable", exc_info=True)
            return 0

    async def reset(self, identity: str) -> None:
        """Clear the counter after a successful authentication."""

        if self.store is None:
            return
        try:
            await self.store.delete(self._key(identity))
        except Exception:  # pragma: no cover - defensive: Redis is optional
            logger.warning("login_rate_limit_unavailable", exc_info=True)
