"""Login brute-force protection.

The limiter is exercised against an in-memory stand-in for Redis rather than a
real one, because the behaviour under test is the decision (block after five
failures, clear on success, stay open when the store is gone) and not the Redis
wire protocol.
"""

from __future__ import annotations

import pytest

from app.security.errors import LoginRateLimitedError
from app.security.rate_limit import KEY_PREFIX, LoginRateLimiter


class FakeStore:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    async def get(self, name: str) -> bytes | None:
        value = self.counters.get(name)
        return None if value is None else str(value).encode()

    async def incr(self, name: str, amount: int = 1) -> int:
        self.counters[name] = self.counters.get(name, 0) + amount
        return self.counters[name]

    async def expire(self, name: str, time: int) -> bool:
        self.expiries[name] = time
        return True

    async def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            if self.counters.pop(name, None) is not None:
                removed += 1
        return removed


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


async def test_five_failures_block_the_origin(store: FakeStore) -> None:
    limiter = LoginRateLimiter(store, limit=5, window_seconds=60)

    for _ in range(4):
        await limiter.check("10.0.0.7")
        await limiter.register_failure("10.0.0.7")

    # The fifth attempt is still allowed; it is the sixth that is refused.
    await limiter.check("10.0.0.7")
    await limiter.register_failure("10.0.0.7")

    with pytest.raises(LoginRateLimitedError) as excinfo:
        await limiter.check("10.0.0.7")

    assert excinfo.value.status_code == 429
    assert excinfo.value.code == "LOGIN_RATE_LIMITED"
    assert excinfo.value.details["retry_after_seconds"] == 60


async def test_the_counter_is_armed_with_a_window(store: FakeStore) -> None:
    limiter = LoginRateLimiter(store, limit=5, window_seconds=45)

    await limiter.register_failure("10.0.0.7")

    assert store.expiries[f"{KEY_PREFIX}10.0.0.7"] == 45


async def test_the_window_is_not_rearmed_on_every_failure(store: FakeStore) -> None:
    """A sliding window per failure would never expire under a slow attacker."""

    limiter = LoginRateLimiter(store, limit=5, window_seconds=45)
    store.expiries.clear()

    await limiter.register_failure("10.0.0.7")
    await limiter.register_failure("10.0.0.7")
    await limiter.register_failure("10.0.0.7")

    assert store.expiries == {f"{KEY_PREFIX}10.0.0.7": 45}


async def test_a_successful_login_clears_the_counter(store: FakeStore) -> None:
    limiter = LoginRateLimiter(store, limit=5, window_seconds=60)
    await limiter.register_failure("10.0.0.7")
    await limiter.register_failure("10.0.0.7")

    await limiter.reset("10.0.0.7")

    assert await limiter.failure_count("10.0.0.7") == 0
    await limiter.check("10.0.0.7")


async def test_origins_are_counted_separately(store: FakeStore) -> None:
    limiter = LoginRateLimiter(store, limit=2, window_seconds=60)
    await limiter.register_failure("10.0.0.7")
    await limiter.register_failure("10.0.0.7")

    # A different origin is unaffected by the first origin's failures.
    await limiter.check("10.0.0.8")
    with pytest.raises(LoginRateLimitedError):
        await limiter.check("10.0.0.7")


async def test_the_limiter_fails_open_when_the_store_is_unavailable() -> None:
    """A cache outage must not lock every operator out of a working platform."""

    limiter = LoginRateLimiter(None, limit=1, window_seconds=60)

    await limiter.register_failure("10.0.0.7")
    await limiter.register_failure("10.0.0.7")
    await limiter.check("10.0.0.7")

    assert await limiter.failure_count("10.0.0.7") == 0


async def test_a_broken_store_does_not_raise() -> None:
    class BrokenStore:
        async def get(self, name: str) -> bytes | None:
            raise ConnectionError("redis is down")

        async def incr(self, name: str, amount: int = 1) -> int:
            raise ConnectionError("redis is down")

        async def expire(self, name: str, time: int) -> bool:
            raise ConnectionError("redis is down")

        async def delete(self, *names: str) -> int:
            raise ConnectionError("redis is down")

    limiter = LoginRateLimiter(BrokenStore(), limit=1, window_seconds=60)

    await limiter.check("10.0.0.7")
    assert await limiter.register_failure("10.0.0.7") == 0
    await limiter.reset("10.0.0.7")
