"""Bounded latest-value fan-out for telemetry clients."""

import asyncio
from collections import defaultdict
from contextlib import suppress

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self, queue_size: int = 1) -> None:
        self.queue_size = queue_size
        self._subscriptions: dict[str, dict[WebSocket, asyncio.Queue[str]]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    async def connect(self, device_id: str, websocket: WebSocket) -> asyncio.Queue[str]:
        await websocket.accept()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self.queue_size)
        async with self._lock:
            self._subscriptions[device_id][websocket] = queue
        return queue

    async def disconnect(self, device_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            subscribers = self._subscriptions.get(device_id)
            if subscribers is None:
                return
            subscribers.pop(websocket, None)
            if not subscribers:
                self._subscriptions.pop(device_id, None)

    async def broadcast(self, device_id: str, payload: str) -> None:
        async with self._lock:
            queues = list(self._subscriptions.get(device_id, {}).values())
        for queue in queues:
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(payload)
