"""Bounded asynchronous retry with deterministic backoff.

Phase 6.10's database-recovery contract: at most three attempts, waiting one,
two, then four seconds between them. Unbounded retry is explicitly forbidden —
a degraded dependency must surface as a failure, not as a queue of callers
hanging forever — so the helper raises :class:`RetryExhaustedError` once the
attempts are spent, chaining the last underlying exception.

The class accepts an injected ``sleep`` so tests can verify the exact backoff
schedule without waiting real seconds.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY_SECONDS = 1.0
DEFAULT_FACTOR = 2.0
#: 1s, 2s, 4s — the schedule the phase mandates for database recovery.
DEFAULT_DELAYS: tuple[float, ...] = (
    DEFAULT_BASE_DELAY_SECONDS,
    DEFAULT_BASE_DELAY_SECONDS * DEFAULT_FACTOR,
    DEFAULT_BASE_DELAY_SECONDS * DEFAULT_FACTOR * DEFAULT_FACTOR,
)


class RetryExhaustedError(RuntimeError):
    """All retry attempts were spent; the last exception is chained."""

    def __init__(self, *, attempts: int, delays: tuple[float, ...]) -> None:
        super().__init__(f"operation failed after {attempts} attempts")
        self.attempts = attempts
        self.delays = delays


class AsyncRetry:
    """Bounded retry around an awaitable factory."""

    def __init__(
        self,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        delays: tuple[float, ...] = DEFAULT_DELAYS,
        exceptions: tuple[type[BaseException], ...] = (Exception,),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.max_attempts = max_attempts
        self.delays = delays
        self.exceptions = exceptions
        self.sleep = sleep

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        """Run ``operation`` up to ``max_attempts`` times with fixed backoff.

        Only the declared exception types are retried. Anything else — notably
        :class:`asyncio.CancelledError` — propagates on the first occurrence,
        so cancellation stays immediate.
        """

        for attempt in range(1, self.max_attempts + 1):
            try:
                return await operation()
            except self.exceptions as exc:
                if attempt >= self.max_attempts:
                    logger.error(
                        "retry_exhausted",
                        extra={"attempts": attempt, "error": str(exc)},
                    )
                    raise RetryExhaustedError(
                        attempts=self.max_attempts, delays=self.delays
                    ) from exc
                delay = self.delays[min(attempt - 1, len(self.delays) - 1)]
                logger.warning(
                    "retry_scheduled",
                    extra={"attempt": attempt, "delay_seconds": delay, "error": str(exc)},
                )
                await self.sleep(delay)
        # Unreachable: the loop either returns or raises.
        raise RetryExhaustedError(attempts=self.max_attempts, delays=self.delays)

    async def __call__(self, operation: Callable[[], Awaitable[T]]) -> T:
        return await self.run(operation)


def default_database_retry(**overrides: Any) -> AsyncRetry:
    """Return the phase-mandated database retry policy: 3 attempts, 1s/2s/4s."""

    return AsyncRetry(max_attempts=DEFAULT_MAX_ATTEMPTS, delays=DEFAULT_DELAYS, **overrides)


__all__ = ["AsyncRetry", "RetryExhaustedError", "default_database_retry"]
