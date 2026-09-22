"""Industrial protocol gateway: device inventory, lifecycle, and status.

The gateway is the runtime owner the Phase 6.5 adapters never had. It reads
declarative device definitions, creates one runtime per device, drives connect and
read through the existing adapter registry, and hands every normalized sample to the
existing ingestion boundary.

The gateway never writes to a device. Start and stop act on the gateway's own
polling runtime only, so no endpoint here can command plant equipment.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from app.gateway.config import load_gateway_config
from app.gateway.errors import GatewayConfigurationError
from app.gateway.ingestion import RegistrationChecker, TelemetrySink
from app.gateway.models import (
    ConnectivitySummary,
    DeviceDefinition,
    DeviceState,
    DeviceStatusRead,
)
from app.gateway.registry import DeviceRegistry
from app.gateway.runtime import DeviceRuntime, RetryPolicy, SimulatorSourceFactory

logger = logging.getLogger(__name__)


class IndustrialProtocolGateway:
    """Own the lifecycle of every configured device runtime."""

    def __init__(
        self,
        *,
        registry: DeviceRegistry,
        sink: TelemetrySink,
        registration: RegistrationChecker,
        enabled: bool = True,
        config_file: str | None = None,
        policy: RetryPolicy | None = None,
        simulator_source_factory: SimulatorSourceFactory | None = None,
        mqtt_connected: Callable[[], bool] | None = None,
    ) -> None:
        self._registry = registry
        self._sink = sink
        self._registration = registration
        self._enabled = enabled
        self._config_file = config_file
        self._policy = policy or RetryPolicy()
        self._simulator_source_factory = simulator_source_factory
        self._mqtt_connected = mqtt_connected
        self._runtimes: dict[str, DeviceRuntime] = {}
        self._loaded_at: datetime | None = None
        for definition in registry.list_definitions():
            self._runtime_for(definition)

    @classmethod
    def from_config_file(
        cls,
        path: Path,
        *,
        sink: TelemetrySink,
        registration: RegistrationChecker,
        enabled: bool = True,
        policy: RetryPolicy | None = None,
        simulator_source_factory: SimulatorSourceFactory | None = None,
        mqtt_connected: Callable[[], bool] | None = None,
    ) -> IndustrialProtocolGateway:
        """Build a gateway from a validated configuration file."""

        registry = DeviceRegistry()
        registry.load(load_gateway_config(path))
        gateway = cls(
            registry=registry,
            sink=sink,
            registration=registration,
            enabled=enabled,
            config_file=path.name,
            policy=policy,
            simulator_source_factory=simulator_source_factory,
            mqtt_connected=mqtt_connected,
        )
        gateway.mark_loaded()
        return gateway

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def config_file(self) -> str | None:
        return self._config_file

    @property
    def loaded_at(self) -> datetime | None:
        return self._loaded_at

    @property
    def registry(self) -> DeviceRegistry:
        return self._registry

    def mark_loaded(self) -> None:
        """Record the moment the configuration became effective."""

        self._loaded_at = datetime.now(UTC)

    def register(self, definition: DeviceDefinition) -> DeviceStatusRead:
        """Register one additional device and return its initial status."""

        self._registry.register(definition)
        return self._runtime_for(definition).status()

    def register_all(self, definitions: Sequence[DeviceDefinition]) -> None:
        """Register a batch of devices atomically."""

        self._registry.load(definitions)
        for definition in definitions:
            self._runtime_for(definition)

    async def start(self) -> None:
        """Start every enabled device, isolating individual failures."""

        for definition in self._registry.enabled():
            runtime = self._runtime_for(definition)
            try:
                await runtime.start()
            except Exception:
                logger.exception(
                    "gateway_device_start_failed", extra={"device_id": definition.device_id}
                )
        if self._loaded_at is None:
            self.mark_loaded()

    async def stop(self) -> None:
        """Stop every device gracefully."""

        results = await asyncio.gather(
            *(runtime.stop() for runtime in self._runtimes.values()),
            return_exceptions=True,
        )
        for outcome in results:
            if isinstance(outcome, BaseException):
                logger.error("gateway_device_stop_failed", exc_info=outcome)

    async def start_device(self, device_id: str) -> DeviceStatusRead:
        """Start one device."""

        runtime = self._require_runtime(device_id)
        await runtime.start()
        return runtime.status()

    async def stop_device(self, device_id: str) -> DeviceStatusRead:
        """Stop one device."""

        runtime = self._require_runtime(device_id)
        await runtime.stop()
        return runtime.status()

    def status(self, device_id: str) -> DeviceStatusRead:
        """Return the status of one device."""

        return self._require_runtime(device_id).status()

    def statuses(self) -> list[DeviceStatusRead]:
        """Return every device status in configuration order."""

        return [self._runtimes[device_id].status() for device_id in self._runtimes]

    def summary(self) -> ConnectivitySummary:
        """Return aggregate inventory and ingestion totals."""

        statuses = self.statuses()
        counts: dict[str, int] = {state.value: 0 for state in DeviceState}
        for status in statuses:
            counts[status.state.value] += 1
        return ConnectivitySummary(
            gateway_enabled=self._enabled,
            gateway_available=True,
            config_file=self._config_file,
            loaded_at=self._loaded_at,
            device_count=len(statuses),
            enabled_device_count=sum(1 for status in statuses if status.enabled),
            states=counts,
            total_samples_ingested=sum(status.samples_ingested for status in statuses),
            total_samples_rejected=sum(status.samples_rejected for status in statuses),
        )

    def _runtime_for(self, definition: DeviceDefinition) -> DeviceRuntime:
        existing = self._runtimes.get(definition.device_id)
        if existing is not None:
            return existing
        runtime = DeviceRuntime(
            definition,
            sink=self._sink,
            registration=self._registration,
            policy=self._policy,
            simulator_source_factory=self._simulator_source_factory,
            mqtt_connected=self._mqtt_connected,
        )
        self._runtimes[definition.device_id] = runtime
        return runtime

    def _require_runtime(self, device_id: str) -> DeviceRuntime:
        runtime = self._runtimes.get(device_id)
        if runtime is None:
            raise GatewayConfigurationError(f"device '{device_id}' is not registered")
        return runtime
