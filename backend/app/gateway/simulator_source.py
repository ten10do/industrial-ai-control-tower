"""Optional in-process simulator source for gateway-polled simulator devices.

The simulator package is deliberately not part of the backend runtime image, so this
module resolves it lazily and returns ``None`` when it is unavailable. A simulator
device without an available source reports ``ERROR`` with an explicit message rather
than inventing measurements.
"""

from __future__ import annotations

import logging
from typing import Any

from app.gateway.runtime import SimulatorSource, SimulatorSourceFactory

logger = logging.getLogger(__name__)


def build_simulator_source_factory() -> SimulatorSourceFactory | None:
    """Return a simulator-backed source factory, or ``None`` when unavailable."""

    try:
        from simulator.models import IndustrialMotor  # type: ignore[import-not-found]
    except ImportError:
        logger.info(
            "simulator_source_unavailable",
            extra={"reason": "simulator package is not importable"},
        )
        return None

    def factory(device_id: str) -> SimulatorSource:
        motor = IndustrialMotor(device_id=device_id)

        def sample() -> dict[str, Any]:
            telemetry = motor.step()
            payload: dict[str, Any] = dict(telemetry.model_dump())
            return payload

        return sample

    return factory
