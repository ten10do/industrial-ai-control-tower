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
from dataclasses import dataclass
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

DEFAULT_APPLY_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class ApplyResult:
    """Outcome of applying one configuration version to a device runtime."""

    device_id: str
    applied: bool
    version: int | None
    state: DeviceState
    error: str | None = None


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
        self._applied_versions: dict[str, int | None] = {}
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

    def applied_version(self, device_id: str) -> int | None:
        """Return the configuration version this device runtime is running."""

        return self._applied_versions.get(device_id)

    def applied_versions(self) -> dict[str, int | None]:
        """Return the applied configuration version of every device."""

        return dict(self._applied_versions)

    async def confirm_ready(
        self,
        device_id: str,
        *,
        version: int | None = None,
        timeout_seconds: float = DEFAULT_APPLY_TIMEOUT_SECONDS,
    ) -> ApplyResult:
        """Wait for an already started device runtime to become usable.

        Used at startup, where the runtime state machine must stay in charge of
        reconnection. The runtime is never torn down on a slow first connection, so
        the Phase 6.7 bounded-retry behaviour is preserved and the result only
        reports whether the device was confirmed connected within the window. The
        version is recorded only on success.
        """

        runtime = self._require_runtime(device_id)
        ready = await runtime.wait_until_ready(timeout_seconds)
        state = runtime.status().state
        if not ready:
            return ApplyResult(
                device_id=device_id,
                applied=False,
                version=None,
                state=state,
                error=runtime.last_failure_message()
                or f"runtime did not report connected within {timeout_seconds:g}s",
            )
        self._applied_versions[device_id] = version
        return ApplyResult(
            device_id=device_id,
            applied=True,
            version=version,
            state=state,
        )

    async def apply_device_definition(
        self,
        definition: DeviceDefinition,
        *,
        version: int | None,
        timeout_seconds: float = DEFAULT_APPLY_TIMEOUT_SECONDS,
    ) -> ApplyResult:
        """Replace one device runtime with a proven-healthy replacement.

        The candidate runtime is built and started first. Only after it reports
        ``CONNECTED`` is the previous runtime stopped and swapped out. When the
        candidate never becomes healthy it is discarded and the previous runtime is
        left untouched, so a bad configuration cannot take a working device down.
        Other devices are never touched.
        """

        device_id = definition.device_id
        if not self._enabled:
            return ApplyResult(
                device_id=device_id,
                applied=False,
                version=version,
                state=DeviceState.DISABLED,
                error="gateway is disabled in this process",
            )
        previous = self._runtimes.get(device_id)
        candidate = DeviceRuntime(
            definition,
            sink=self._sink,
            registration=self._registration,
            policy=self._policy,
            simulator_source_factory=self._simulator_source_factory,
            mqtt_connected=self._mqtt_connected,
        )
        try:
            await candidate.start()
        except Exception as exc:  # defensive: apply must never break the gateway
            logger.exception("gateway_apply_start_failed", extra={"device_id": device_id})
            await candidate.stop()
            return ApplyResult(
                device_id=device_id,
                applied=False,
                version=version,
                state=DeviceState.ERROR,
                error=f"candidate runtime could not start: {exc}",
            )
        ready = await candidate.wait_until_ready(timeout_seconds)
        if not ready:
            reason = candidate.last_failure_message() or (
                f"candidate runtime was not connected within {timeout_seconds:g}s"
            )
            await candidate.stop()
            logger.warning(
                "gateway_apply_not_ready", extra={"device_id": device_id, "detail": reason}
            )
            return ApplyResult(
                device_id=device_id,
                applied=False,
                version=version,
                state=candidate.status().state,
                error=reason,
            )
        if previous is not None:
            await previous.stop()
        self._runtimes[device_id] = candidate
        self._registry.replace(definition)
        self._applied_versions[device_id] = version
        logger.info(
            "gateway_configuration_applied",
            extra={"device_id": device_id, "configuration_version": version},
        )
        return ApplyResult(
            device_id=device_id,
            applied=True,
            version=version,
            state=candidate.status().state,
        )

    async def apply_definitions(
        self,
        definitions: Sequence[tuple[DeviceDefinition, int | None]],
        *,
        timeout_seconds: float = DEFAULT_APPLY_TIMEOUT_SECONDS,
    ) -> list[ApplyResult]:
        """Apply a batch of definitions, isolating individual failures."""

        results: list[ApplyResult] = []
        for definition, version in definitions:
            results.append(
                await self.apply_device_definition(
                    definition, version=version, timeout_seconds=timeout_seconds
                )
            )
        return results

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
