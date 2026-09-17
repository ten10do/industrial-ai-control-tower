"""Latest telemetry cache with atomic stale-write protection."""

import json

from redis.asyncio import Redis

from app.schemas.telemetry import TelemetryRead

_SET_IF_NEWER = """
local existing = redis.call('HGET', KEYS[1], 'timestamp_epoch')
if existing and tonumber(existing) >= tonumber(ARGV[1]) then
  return 0
end
redis.call('HSET', KEYS[1], 'timestamp_epoch', ARGV[1], 'payload', ARGV[2])
return 1
"""


class LatestTelemetryCache:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    @staticmethod
    def key(device_id: str) -> str:
        return f"device:{device_id}:latest"

    async def set_if_newer(self, telemetry: TelemetryRead) -> bool:
        result = await self.redis.eval(
            _SET_IF_NEWER,
            1,
            self.key(telemetry.device_id),
            telemetry.timestamp.timestamp(),
            telemetry.model_dump_json(),
        )
        return bool(result)

    async def get(self, device_id: str) -> TelemetryRead | None:
        raw = await self.redis.hget(self.key(device_id), "payload")
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return TelemetryRead.model_validate(json.loads(raw))
