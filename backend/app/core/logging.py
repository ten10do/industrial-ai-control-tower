"""Small JSON logging setup with correlation fields."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.context import trace_id_context


class JsonFormatter(logging.Formatter):
    """Serialize stable operational fields without logging message payloads."""

    _reserved = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": "backend",
            "trace_id": getattr(record, "trace_id", trace_id_context.get()),
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._reserved and key not in {"message", "asctime", "trace_id"}:
                data[key] = value
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str, separators=(",", ":"))


def configure_logging(level: str) -> None:
    """Configure the root logger exactly once for application startup."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
