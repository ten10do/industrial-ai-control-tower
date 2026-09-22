"""Read-only Modbus TCP adapter backed by pymodbus."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any

from pydantic import ValidationError
from pymodbus.client import AsyncModbusTcpClient

from adapters.base import IndustrialProtocolAdapter
from adapters.exceptions import (
    AdapterConfigurationError,
    AdapterConnectionError,
    AdapterReadError,
)
from adapters.models import (
    AdapterHealth,
    AdapterStatus,
    ProtocolType,
    SignalQuality,
    UnifiedTelemetry,
)

FIRST_HOLDING_REGISTER = 40001


@dataclass(frozen=True)
class RegisterMapping:
    """Validated configuration for one holding-register signal."""

    address: int
    scale: float
    unit: str | None

    @property
    def protocol_address(self) -> int:
        return self.address - FIRST_HOLDING_REGISTER


class ModbusTcpAdapter(IndustrialProtocolAdapter):
    """Read configured holding registers without exposing control operations."""

    def __init__(
        self,
        host: str,
        port: int,
        device_id: str,
        registers: Mapping[str, Mapping[str, Any]],
        unit_id: int = 1,
        timeout_seconds: float = 3.0,
    ) -> None:
        if not host.strip():
            raise AdapterConfigurationError("Modbus host must not be blank.")
        if isinstance(port, bool) or not 1 <= port <= 65535:
            raise AdapterConfigurationError("Modbus port must be between 1 and 65535.")
        if not device_id.strip():
            raise AdapterConfigurationError("Modbus device_id must not be blank.")
        if isinstance(unit_id, bool) or not 1 <= unit_id <= 247:
            raise AdapterConfigurationError("Modbus unit_id must be between 1 and 247.")
        if timeout_seconds <= 0:
            raise AdapterConfigurationError("Modbus timeout_seconds must be positive.")
        self.host = host
        self.port = port
        self.device_id = device_id
        self.unit_id = unit_id
        self.timeout_seconds = timeout_seconds
        self._registers = self._normalize_registers(registers)
        self._client: AsyncModbusTcpClient | None = None
        self._status = AdapterStatus.DISCONNECTED
        self._last_success: datetime | None = None
        self._last_error: datetime | None = None
        self._message: str | None = None

    @staticmethod
    def _normalize_registers(
        registers: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, RegisterMapping]:
        normalized: dict[str, RegisterMapping] = {}
        for signal, definition in registers.items():
            address = definition.get("address")
            scale = definition.get("scale")
            unit = definition.get("unit")
            if not signal.strip():
                raise AdapterConfigurationError("Modbus signal names must not be blank.")
            if (
                isinstance(address, bool)
                or not isinstance(address, int)
                or not FIRST_HOLDING_REGISTER <= address <= FIRST_HOLDING_REGISTER + 65535
            ):
                raise AdapterConfigurationError(
                    "Modbus holding-register addresses must map to offsets 0 through 65535."
                )
            if isinstance(scale, bool) or not isinstance(scale, int | float):
                raise AdapterConfigurationError("Modbus register scales must be numeric.")
            numeric_scale = float(scale)
            if not isfinite(numeric_scale):
                raise AdapterConfigurationError("Modbus register scales must be finite.")
            if unit is not None and not isinstance(unit, str):
                raise AdapterConfigurationError("Modbus register units must be strings.")
            normalized[signal] = RegisterMapping(address, numeric_scale, unit)
        if not normalized:
            raise AdapterConfigurationError("Modbus register mapping must not be empty.")
        return normalized

    @property
    def protocol(self) -> ProtocolType:
        return ProtocolType.MODBUS_TCP

    async def connect(self) -> None:
        if self._status is AdapterStatus.CONNECTED:
            return
        client = AsyncModbusTcpClient(
            self.host,
            port=self.port,
            timeout=self.timeout_seconds,
            retries=0,
            reconnect_delay=0,
        )
        try:
            connected = await client.connect()
        except Exception as exc:
            client.close()
            self._record_error("Modbus TCP connection failed.")
            raise AdapterConnectionError(self._message) from exc
        if not connected:
            client.close()
            self._record_error("Modbus TCP connection failed.")
            raise AdapterConnectionError(self._message)
        self._client = client
        self._status = AdapterStatus.CONNECTED
        self._message = None

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            client.close()
        self._status = AdapterStatus.DISCONNECTED
        self._message = None

    async def read(self) -> UnifiedTelemetry:
        if self._client is None or self._status is not AdapterStatus.CONNECTED:
            raise AdapterConnectionError("Modbus TCP adapter is not connected.")
        try:
            signals: dict[str, float] = {}
            for signal, mapping in self._registers.items():
                response = await self._client.read_holding_registers(
                    mapping.protocol_address,
                    count=1,
                    device_id=self.unit_id,
                )
                if response.isError() or not hasattr(response, "registers"):
                    raise AdapterReadError(f"Modbus register {mapping.address} could not be read.")
                signals[signal] = float(response.registers[0]) * mapping.scale
            telemetry = UnifiedTelemetry(
                device_id=self.device_id,
                timestamp=datetime.now(UTC),
                signals=signals,
                source_protocol=self.protocol,
                quality=SignalQuality.GOOD,
                metadata={
                    "host": self.host,
                    "port": self.port,
                    "unit_id": self.unit_id,
                    "registers": {
                        signal: {
                            "address": mapping.address,
                            "scale": mapping.scale,
                            "unit": mapping.unit,
                        }
                        for signal, mapping in self._registers.items()
                    },
                },
            )
        except (AdapterReadError, ValidationError) as exc:
            self._record_error("Modbus TCP values could not be normalized.")
            raise AdapterReadError(self._message) from exc
        except Exception as exc:
            self._record_error("Modbus TCP register read failed.")
            raise AdapterReadError(self._message) from exc
        self._status = AdapterStatus.CONNECTED
        self._last_success = datetime.now(UTC)
        self._message = None
        return telemetry

    def _record_error(self, message: str) -> None:
        self._status = AdapterStatus.ERROR
        self._last_error = datetime.now(UTC)
        self._message = message

    def health(self) -> AdapterHealth:
        return AdapterHealth(
            protocol=self.protocol,
            status=self._status,
            last_success=self._last_success,
            last_error=self._last_error,
            message=self._message,
            host=self.host,
            port=self.port,
        )
