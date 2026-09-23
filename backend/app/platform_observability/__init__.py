"""Platform-level observability, distinct from Agent Observability.

``app.observability`` owns the agent-run tracing that Phase 6.6 introduced and
must not be touched. This package is the Phase 6.10 platform layer: Prometheus
metrics for the infrastructure plane (gateway adapters, telemetry ingestion,
alarms, incidents, workflows), the ``/metrics`` exposition endpoint, monitored
background tasks, and the bounded database retry helper.

Everything here is instrumentation only. No hook changes business logic: each
call site gains one counter/gauge/histogram update next to an existing log or
state transition.
"""

from app.platform_observability.metrics import (
    adapter_connect_failure_total,
    adapter_connect_success_total,
    adapter_last_success_timestamp,
    adapter_read_latency_seconds,
    alarm_active_count,
    alarm_cleared_total,
    alarm_created_total,
    background_task_failure_total,
    incident_active_count,
    incident_created_total,
    incident_resolved_total,
    mqtt_reconnect_total,
    telemetry_ingest_failed_total,
    telemetry_ingest_total,
    telemetry_processing_latency_seconds,
    workflow_failed_total,
    workflow_started_total,
    workflow_waiting_approval_total,
)
from app.platform_observability.resilience import AsyncRetry, RetryExhaustedError
from app.platform_observability.tasks import monitor_background_task

__all__ = [
    "AsyncRetry",
    "RetryExhaustedError",
    "adapter_connect_failure_total",
    "adapter_connect_success_total",
    "adapter_last_success_timestamp",
    "adapter_read_latency_seconds",
    "alarm_active_count",
    "alarm_cleared_total",
    "alarm_created_total",
    "background_task_failure_total",
    "incident_active_count",
    "incident_created_total",
    "incident_resolved_total",
    "monitor_background_task",
    "mqtt_reconnect_total",
    "telemetry_ingest_failed_total",
    "telemetry_ingest_total",
    "telemetry_processing_latency_seconds",
    "workflow_failed_total",
    "workflow_started_total",
    "workflow_waiting_approval_total",
]
