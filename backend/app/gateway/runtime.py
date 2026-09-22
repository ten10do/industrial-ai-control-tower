"""Per-device runtime: lifecycle state machine, polling, and bounded retry.

Each device owns one asyncio task. Failures are isolated per device: a device that
cannot connect, cannot read, or produces samples the ingestion contract rejects
moves through ``DEGRADED``, ``RECONNECTING`` and finally ``ERROR`` without affecting
any other device.

MQTT devices are passive. They keep their existing push semantics, so the gateway
never polls them and never constructs an adapter for them. Their state mirrors the
shared MQTT consumer connection instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from adapters.base import IndustrialProtocolAdapter
from adapters.exceptions import AdapterError
from adapters.models import ProtocolType, UnifiedTelemetry
from adapters.registry import create_adapter
from app.gateway.errors import GatewayConfigurationError
from app.gateway.ingestion import IngestionOutcome, RegistrationChecker, TelemetrySink
from app.gateway.models import DeviceDefinition, DeviceState, DeviceStatusRead

logger = logging.getLogger(__name__)

SimulatorSource = Callable[[], Mapping[str, Any]]
SimulatorSourceFactory = Callable[[str], SimulatorSource]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retry and backoff behaviour shared by every device runtime.

    Backoff is deterministic exponential growth without jitter. Jitter is omitted
    deliberately so the schedule is reproducible in tests and so the bounded delay
    is directly observable by an operator.
    """

    failure_threshold: int = 3
    reconnect_threshold: int = 6
    max_reconnect_attempts: int = 5
    backoff_initial_seconds: float = 1.0
    backoff_max_seconds: float = 30.0
    backoff_factor: float = 2.0

    def delay_for(self, attempt: int) -> float:
        """Return the bounded delay before reconnection attempt number ``attempt``."""

        bounded_attempt = max(attempt, 0)
        return min(
            self.backoff_initial_seconds * (self.backoff_factor**bounded_attempt),
            self.backoff_max_seconds,
        )


class DeviceRuntime:
    """Own one device's adapter, polling loop, and lifecycle state."""

    def __init__(
        self,
        definition: DeviceDefinition,
        *,
        sink: TelemetrySink,
        registration: RegistrationChecker,
        policy: RetryPolicy | None = None,
        simulator_source_factory: SimulatorSourceFactory | None = None,
        mqtt_connected: Callable[[], bool] | None = None,
    ) -> None:
        self._definition = definition
        self._sink = sink
        self._registration = registration
        self._policy = policy or RetryPolicy()
        self._simulator_source_factory = simulator_source_factory
        self._mqtt_connected = mqtt_connected
        self._task: asyncio.Task[None] | None = None
        self._adapter: IndustrialProtocolAdapter | None = None
        self._state: DeviceState = DeviceState.STOPPED
        self._last_success: datetime | None = None
        self._last_error: datetime | None = None
        self._message: str | None = None
        self._consecutive_failures = 0
        self._reconnect_attempts = 0
        self._samples_ingested = 0
        self._samples_rejected = 0
        self._read_errors = 0

    @property
    def device_id(self) -> str:
        return self._definition.device_id

    @property
    def definition(self) -> DeviceDefinition:
        return self._definition

    @property
    def running(self) -> bool:
        """Return whether a polling task is currently active."""

        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start this device idempotently."""

        if not self._definition.enabled:
            self._state = DeviceState.DISABLED
            self._message = "device is disabled in configuration"
            return
        if self.running:
            return
        if not self._definition.polled:
            self._state = self._passive_state()
            self._message = (
                None
                if self._state is DeviceState.CONNECTED
                else "shared MQTT consumer is not connected"
            )
            return
        self._state = DeviceState.STARTING
        self._message = None
        self._task = asyncio.create_task(self._run(), name=f"gateway-{self.device_id}")

    async def stop(self) -> None:
        """Stop this device gracefully and release its connection."""

        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        adapter, self._adapter = self._adapter, None
        if adapter is not None:
            await self._teardown(adapter)
        if self._definition.enabled:
            self._state = DeviceState.STOPPED if self._definition.polled else self._passive_state()
        else:
            self._state = DeviceState.DISABLED
        self._message = None

    def status(self) -> DeviceStatusRead:
        """Return a read-only status snapshot."""

        return DeviceStatusRead(
            device_id=self.device_id,
            protocol=self._definition.protocol,
            enabled=self._definition.enabled,
            state=self._current_state(),
            state_mode=self._definition.state.mode,
            polled=self._definition.polled,
            poll_interval_ms=self._definition.poll_interval_ms,
            endpoint=self._definition.endpoint,
            last_success=self._last_success,
            last_error=self._last_error,
            message=self._message,
            consecutive_failures=self._consecutive_failures,
            reconnect_attempts=self._reconnect_attempts,
            samples_ingested=self._samples_ingested,
            samples_rejected=self._samples_rejected,
            read_errors=self._read_errors,
        )

    def _current_state(self) -> DeviceState:
        if not self._definition.enabled:
            return DeviceState.DISABLED
        if not self._definition.polled:
            return self._passive_state()
        return self._state

    def _passive_state(self) -> DeviceState:
        if self._mqtt_connected is None:
            return DeviceState.DEGRADED
        return DeviceState.CONNECTED if self._mqtt_connected() else DeviceState.DEGRADED

    async def _run(self) -> None:
        definition = self._definition
        try:
            if not await self._registration.exists(self.device_id):
                self._fail_permanently(
                    f"device '{self.device_id}' is not registered in the devices table"
                )
                return
            try:
                adapter = self._build_adapter()
            except (GatewayConfigurationError, AdapterError, ValueError, TypeError) as exc:
                self._fail_permanently(f"adapter could not be constructed: {exc}")
                return
            self._adapter = adapter
            while True:
                self._state = DeviceState.CONNECTING
                try:
                    await adapter.connect()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._last_error = _now()
                    self._message = f"connection failed: {exc}"
                    logger.warning(
                        "gateway_connect_failed",
                        extra={"device_id": self.device_id, "error": str(exc)},
                    )
                    if not await self._retreat("connection"):
                        return
                    continue
                self._consecutive_failures = 0
                self._reconnect_attempts = 0
                self._state = DeviceState.CONNECTED
                self._message = None
                logger.info(
                    "gateway_device_connected",
                    extra={"device_id": self.device_id, "protocol": definition.protocol.value},
                )
                await self._poll_loop(adapter)
                await self._teardown(adapter)
                if not await self._retreat("telemetry"):
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # defensive: a runtime must never take down the app
            logger.exception("gateway_runtime_failed", extra={"device_id": self.device_id})
            self._fail_permanently(f"unexpected runtime failure: {exc}")
        finally:
            current = self._adapter
            self._adapter = None
            if current is not None:
                await self._teardown(current)

    async def _poll_loop(self, adapter: IndustrialProtocolAdapter) -> None:
        """Poll until the reconnect threshold is reached.

        Returns only when consecutive failures reach ``reconnect_threshold``, so the
        caller always re-establishes the connection. Cancellation propagates.
        """

        interval = self._definition.poll_interval_ms / 1000.0
        while True:
            try:
                telemetry = await adapter.read()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._read_errors += 1
                self._last_error = _now()
                self._message = f"read failed: {exc}"
                if self._record_failure():
                    return
            else:
                if await self._publish(telemetry) and self._record_failure():
                    return
            await asyncio.sleep(interval)

    async def _publish(self, telemetry: UnifiedTelemetry) -> bool:
        """Submit one sample. Return ``True`` when it counted as a failure."""

        try:
            outcome = await self._sink.publish(telemetry, self._definition.state)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_error = _now()
            self._message = f"ingestion failed: {exc}"
            logger.exception("gateway_ingestion_failed", extra={"device_id": self.device_id})
            return True
        if outcome is IngestionOutcome.REJECTED:
            self._samples_rejected += 1
            self._last_error = _now()
            self._message = "sample was rejected by the ingestion contract"
            return True
        self._samples_ingested += 1
        self._last_success = _now()
        self._consecutive_failures = 0
        self._state = DeviceState.CONNECTED
        self._message = None
        return False

    def _record_failure(self) -> bool:
        """Count a failure. Return ``True`` when reconnection is required."""

        self._consecutive_failures += 1
        if self._consecutive_failures >= self._policy.reconnect_threshold:
            self._state = DeviceState.RECONNECTING
            return True
        if self._consecutive_failures >= self._policy.failure_threshold:
            self._state = DeviceState.DEGRADED
        return False

    async def _retreat(self, stage: str) -> bool:
        """Wait a bounded backoff interval. Return ``False`` when the device must fail."""

        if self._reconnect_attempts >= self._policy.max_reconnect_attempts:
            self._fail_permanently(
                f"{stage} recovery exhausted after "
                f"{self._reconnect_attempts} attempts: {self._message or 'unknown cause'}"
            )
            return False
        self._state = DeviceState.RECONNECTING
        delay = self._policy.delay_for(self._reconnect_attempts)
        self._reconnect_attempts += 1
        await asyncio.sleep(delay)
        self._consecutive_failures = 0
        return True

    def _build_adapter(self) -> IndustrialProtocolAdapter:
        definition = self._definition
        if definition.protocol is ProtocolType.SIMULATOR:
            if self._simulator_source_factory is None:
                raise GatewayConfigurationError(
                    "no simulator sample source is registered in this process"
                )
            return create_adapter(
                ProtocolType.SIMULATOR,
                source=self._simulator_source_factory(definition.device_id),
            )
        if definition.modbus_tcp is not None:
            modbus = definition.modbus_tcp
            return create_adapter(
                ProtocolType.MODBUS_TCP,
                host=modbus.host,
                port=modbus.port,
                device_id=definition.device_id,
                registers={
                    signal: {
                        "address": register.address,
                        "scale": register.scale,
                        "unit": register.unit,
                    }
                    for signal, register in modbus.registers.items()
                },
                unit_id=modbus.unit_id,
                timeout_seconds=modbus.timeout_seconds,
            )
        if definition.opc_ua is not None:
            opcua = definition.opc_ua
            return create_adapter(
                ProtocolType.OPC_UA,
                endpoint=opcua.endpoint,
                device_id=definition.device_id,
                nodes={signal: {"node_id": node.node_id} for signal, node in opcua.nodes.items()},
                timeout_seconds=opcua.timeout_seconds,
            )
        raise GatewayConfigurationError(
            f"device '{definition.device_id}' has no pollable protocol configuration"
        )

    async def _teardown(self, adapter: IndustrialProtocolAdapter) -> None:
        try:
            await adapter.disconnect()
        except Exception:
            logger.exception("gateway_disconnect_failed", extra={"device_id": self.device_id})

    def _fail_permanently(self, message: str) -> None:
        self._state = DeviceState.ERROR
        self._last_error = _now()
        self._message = message
        logger.error("gateway_device_error", extra={"device_id": self.device_id, "detail": message})
