"""Per-device live telemetry WebSocket."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.repositories.device import DeviceRepository

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/devices/{device_id}/telemetry")
async def device_telemetry(websocket: WebSocket, device_id: str) -> None:
    database = websocket.app.state.database
    async with database.sessions() as session:
        if await DeviceRepository(session).get(device_id) is None:
            await websocket.close(code=4404, reason="Device not found")
            return
    manager = websocket.app.state.websocket_manager
    queue = await manager.connect(device_id, websocket)
    try:
        while True:
            await websocket.send_text(await queue.get())
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(device_id, websocket)
