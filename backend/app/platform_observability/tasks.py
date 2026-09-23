"""Bounded background-task monitoring.

An ``asyncio.create_task`` whose coroutine dies with an exception is silent by
default: the exception sits in the task until it is garbage collected, printing
"Task exception was never retrieved" long after the fact — or never, if
something keeps a reference. ``monitor_background_task`` attaches a done
callback that surfaces the outcome immediately: cancellation is expected and
logged at info, any other exception is logged with the traceback and counted in
``background_task_failure_total``. The counter is what turns a silent worker
death into something an alert can fire on.
"""

from __future__ import annotations

import asyncio
import logging

from app.platform_observability.metrics import background_task_failure_total

logger = logging.getLogger(__name__)


def monitor_background_task(task: asyncio.Task[None], *, name: str) -> asyncio.Task[None]:
    """Attach the failure callback and return the task unchanged."""

    task.add_done_callback(lambda done: _report(done, name))
    return task


def _report(task: asyncio.Task[None], name: str) -> None:
    if task.cancelled():
        logger.info("background_task_cancelled", extra={"task": name})
        return
    exc = task.exception()
    if exc is None:
        return
    background_task_failure_total.labels(task=name).inc()
    logger.error(
        "background_task_failed",
        extra={"task": name, "error": str(exc)},
        exc_info=exc,
    )


__all__ = ["monitor_background_task"]
