"""Request and ingestion correlation context."""

from contextvars import ContextVar

trace_id_context: ContextVar[str] = ContextVar("trace_id", default="-")
