"""Read-only deterministic Modbus TCP server used by tests and development."""

from types import TracebackType

from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice

from simulator.modbus.registers import DEVICE_ID, holding_register_values


class ModbusTcpServerSimulator:
    """Expose deterministic motor telemetry through read-only holding registers."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5020,
        device_id: int = DEVICE_ID,
    ) -> None:
        self.host = host
        self.port = port
        self.device_id = device_id
        self._server: ModbusTcpServer | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    async def start(self) -> None:
        if self.running:
            return
        registers = SimData(
            address=0,
            values=holding_register_values(),
            datatype=DataType.REGISTERS,
            readonly=True,
        )
        server = ModbusTcpServer(
            SimDevice(self.device_id, registers),
            address=(self.host, self.port),
        )
        await server.serve_forever(background=True)
        self._server = server

    async def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            await server.shutdown()  # type: ignore[no-untyped-call]

    async def __aenter__(self) -> "ModbusTcpServerSimulator":
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.stop()
