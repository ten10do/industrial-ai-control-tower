"""Phase 6.7 industrial protocol gateway contracts.

The gateway drives the Phase 6.5 adapters from declarative device definitions and
hands every normalized sample to the existing ingestion boundary. These models
reuse ``adapters.models.ProtocolType`` instead of declaring a second protocol enum,
and they reuse the canonical signal vocabulary already emitted by the adapters.

Signal coverage is mandatory. The canonical telemetry contract requires eight
numeric signals and its storage columns are ``NOT NULL``, so a device definition
that cannot supply all eight is rejected at load time. The gateway never fills
missing measurements with defaults.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from adapters.models import ProtocolType

CANONICAL_SIGNAL_FIELDS: tuple[str, ...] = (
    "temperature",
    "bearing_temperature",
    "vibration",
    "current",
    "voltage",
    "rpm",
    "load",
    "power",
)

_CANONICAL_SIGNALS = frozenset(CANONICAL_SIGNAL_FIELDS)

FIRST_HOLDING_REGISTER = 40001
_MAX_HOLDING_REGISTER = FIRST_HOLDING_REGISTER + 65535


class DeviceState(StrEnum):
    """Lifecycle state of one gateway-managed device runtime."""

    DISABLED = "DISABLED"
    STARTING = "STARTING"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


def _require_full_coverage(mapping: dict[str, Any], protocol: str) -> None:
    """Reject definitions that cannot supply every canonical signal."""

    present = set(mapping)
    unknown = sorted(present - _CANONICAL_SIGNALS)
    missing = sorted(_CANONICAL_SIGNALS - present)
    problems: list[str] = []
    if unknown:
        problems.append("unknown signals: " + ", ".join(unknown))
    if missing:
        problems.append("missing canonical signals: " + ", ".join(missing))
    if problems:
        raise ValueError(
            f"{protocol} signal mapping must map exactly the canonical signals; "
            + "; ".join(problems)
        )


class StateRule(BaseModel):
    """Derive a state label from one measured canonical signal."""

    model_config = ConfigDict(extra="forbid")

    target: Literal["operating_state", "fault_state"]
    signal: str
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte"] = "gt"
    threshold: float
    then: str = Field(min_length=1, max_length=100)

    @field_validator("signal")
    @classmethod
    def known_signal(cls, value: str) -> str:
        if value not in _CANONICAL_SIGNALS:
            raise ValueError(f"derived state rules require a canonical signal, got '{value}'")
        return value

    def matches(self, measurement: float) -> bool:
        """Return whether the measured value satisfies this rule."""

        comparisons: dict[str, bool] = {
            "eq": measurement == self.threshold,
            "ne": measurement != self.threshold,
            "gt": measurement > self.threshold,
            "gte": measurement >= self.threshold,
            "lt": measurement < self.threshold,
            "lte": measurement <= self.threshold,
        }
        return comparisons[self.operator]


class DeviceStateDefinition(BaseModel):
    """Static state labels plus optional rules that derive them from measurements.

    The static labels are always required, so a device always has an honest value
    to publish. Rules are evaluated first, in declaration order, and the first rule
    matching a target wins; when no rule matches, the static label is used.
    """

    model_config = ConfigDict(extra="forbid")

    operating_state: str = Field(min_length=1, max_length=50)
    fault_state: str = Field(min_length=1, max_length=100)
    derived: list[StateRule] = Field(default_factory=list)

    @property
    def mode(self) -> Literal["static", "derived"]:
        return "derived" if self.derived else "static"


class ModbusRegisterConfig(BaseModel):
    """One holding-register mapping."""

    model_config = ConfigDict(extra="forbid")

    address: int = Field(ge=FIRST_HOLDING_REGISTER, le=_MAX_HOLDING_REGISTER)
    scale: float
    unit: str | None = None

    @field_validator("scale")
    @classmethod
    def finite_scale(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("register scale must be finite")
        return value


class ModbusDeviceConfig(BaseModel):
    """Read-only Modbus TCP connection parameters."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    unit_id: int = Field(default=1, ge=1, le=247)
    timeout_seconds: float = Field(default=3.0, gt=0)
    registers: dict[str, ModbusRegisterConfig]

    @field_validator("registers")
    @classmethod
    def full_signal_coverage(
        cls, value: dict[str, ModbusRegisterConfig]
    ) -> dict[str, ModbusRegisterConfig]:
        _require_full_coverage(value, "modbus_tcp")
        return value


class OpcUaNodeConfig(BaseModel):
    """One OPC UA node mapping."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)


class OpcUaDeviceConfig(BaseModel):
    """Read-only OPC UA connection parameters."""

    model_config = ConfigDict(extra="forbid")

    endpoint: str
    timeout_seconds: float = Field(default=4.0, gt=0)
    nodes: dict[str, OpcUaNodeConfig]

    @field_validator("endpoint")
    @classmethod
    def opc_tcp_endpoint(cls, value: str) -> str:
        if not value.startswith("opc.tcp://"):
            raise ValueError("OPC UA endpoint must use opc.tcp://")
        return value

    @field_validator("nodes")
    @classmethod
    def full_signal_coverage(cls, value: dict[str, OpcUaNodeConfig]) -> dict[str, OpcUaNodeConfig]:
        _require_full_coverage(value, "opc_ua")
        return value


class SimulatorDeviceConfig(BaseModel):
    """Simulator device parameters.

    The sample source is injected by the application because the simulator package
    is not part of the backend runtime image. A simulator device without an
    injected source reports ``ERROR`` rather than inventing measurements.
    """

    model_config = ConfigDict(extra="forbid")


class MqttDeviceConfig(BaseModel):
    """MQTT inventory entry.

    MQTT keeps its existing push semantics: the gateway never polls it and never
    constructs an adapter for it. The topic is informative only.
    """

    model_config = ConfigDict(extra="forbid")

    topic: str | None = None


class DeviceDefinition(BaseModel):
    """Declarative onboarding definition for one industrial device."""

    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    protocol: ProtocolType
    enabled: bool = True
    poll_interval_ms: int = Field(default=1000, ge=100, le=3_600_000)
    state: DeviceStateDefinition

    modbus_tcp: ModbusDeviceConfig | None = None
    opc_ua: OpcUaDeviceConfig | None = None
    simulator: SimulatorDeviceConfig | None = None
    mqtt: MqttDeviceConfig | None = None

    @model_validator(mode="after")
    def require_matching_protocol_block(self) -> Self:
        blocks: dict[ProtocolType, BaseModel | None] = {
            ProtocolType.MODBUS_TCP: self.modbus_tcp,
            ProtocolType.OPC_UA: self.opc_ua,
            ProtocolType.SIMULATOR: self.simulator,
            ProtocolType.MQTT: self.mqtt,
        }
        if blocks[self.protocol] is None:
            raise ValueError(
                f"device '{self.device_id}' must declare a '{self.protocol.value}' block"
            )
        unexpected = sorted(
            protocol.value
            for protocol, block in blocks.items()
            if protocol is not self.protocol and block is not None
        )
        if unexpected:
            raise ValueError(
                f"device '{self.device_id}' declares blocks that do not match protocol "
                f"'{self.protocol.value}': {', '.join(unexpected)}"
            )
        return self

    @property
    def endpoint(self) -> str | None:
        """Return a human-readable, non-secret endpoint description."""

        if self.modbus_tcp is not None:
            return f"{self.modbus_tcp.host}:{self.modbus_tcp.port}"
        if self.opc_ua is not None:
            return self.opc_ua.endpoint
        return None

    @property
    def polled(self) -> bool:
        """Return whether the gateway polls this device."""

        return self.protocol is not ProtocolType.MQTT


class DeviceStatusRead(BaseModel):
    """Read-only status of one gateway-managed device."""

    model_config = ConfigDict(extra="forbid")

    device_id: str
    protocol: ProtocolType
    enabled: bool
    state: DeviceState
    state_mode: Literal["static", "derived"]
    polled: bool
    poll_interval_ms: int
    endpoint: str | None = None
    last_success: datetime | None = None
    last_error: datetime | None = None
    message: str | None = None
    consecutive_failures: int = 0
    reconnect_attempts: int = 0
    samples_ingested: int = 0
    samples_rejected: int = 0
    read_errors: int = 0


class ConnectivitySummary(BaseModel):
    """Aggregate gateway inventory and ingestion totals."""

    model_config = ConfigDict(extra="forbid")

    gateway_enabled: bool
    gateway_available: bool
    gateway_error: str | None = None
    config_file: str | None = None
    loaded_at: datetime | None = None
    device_count: int = 0
    enabled_device_count: int = 0
    states: dict[str, int] = Field(default_factory=dict)
    total_samples_ingested: int = 0
    total_samples_rejected: int = 0
