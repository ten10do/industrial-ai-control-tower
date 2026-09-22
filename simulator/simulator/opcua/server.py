"""Read-only deterministic OPC UA server used by tests and local development."""

from types import TracebackType

from asyncua import ua
from asyncua.common.node import Node
from asyncua.server.server import Server

from simulator.opcua.nodes import (
    DETERMINISTIC_VALUES,
    DEVICE_ID,
    NAMESPACE_URI,
    NODE_BROWSE_NAMES,
    node_identifier,
)


class OpcUaServerSimulator:
    """Expose deterministic motor telemetry as read-only OPC UA variables."""

    def __init__(
        self,
        endpoint: str = "opc.tcp://127.0.0.1:4840/industrial-ai/",
        device_id: str = DEVICE_ID,
    ) -> None:
        self.endpoint = endpoint
        self.device_id = device_id
        self._server: Server | None = None
        self._namespace_index: int | None = None
        self._nodes: dict[str, Node] = {}

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def node_ids(self) -> dict[str, str]:
        if self._namespace_index is None:
            return {}
        return {
            signal: f"ns={self._namespace_index};s={node_identifier(signal, self.device_id)}"
            for signal in NODE_BROWSE_NAMES
        }

    async def start(self) -> None:
        if self.running:
            return
        server = Server()
        await server.init()
        server.set_endpoint(self.endpoint)
        namespace_index = await server.register_namespace(NAMESPACE_URI)
        device = await server.nodes.objects.add_object(
            ua.NodeId.from_string(f"ns={namespace_index};s={self.device_id}"),
            ua.QualifiedName.from_string(f"{namespace_index}:{self.device_id}"),
        )
        nodes: dict[str, Node] = {}
        for signal, browse_name in NODE_BROWSE_NAMES.items():
            nodes[signal] = await device.add_variable(
                ua.NodeId.from_string(
                    f"ns={namespace_index};s={node_identifier(signal, self.device_id)}"
                ),
                ua.QualifiedName.from_string(f"{namespace_index}:{browse_name}"),
                DETERMINISTIC_VALUES[signal],
            )
        await server.start()
        self._server = server
        self._namespace_index = namespace_index
        self._nodes = nodes

    async def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            await server.stop()
        self._namespace_index = None
        self._nodes = {}

    async def __aenter__(self) -> "OpcUaServerSimulator":
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.stop()
