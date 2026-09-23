"""Prometheus metric registry for the platform plane.

One module, one registry, one naming convention. Counters end in ``_total``,
histograms in ``_seconds``, gauges carry an explicit unit. Labels are limited
to identity dimensions (``device_id``, ``protocol``, ``result``) so cardinality
stays bounded by the device count, not by the event count.

The active-count gauges (``alarm_active_count``, ``incident_active_count``)
are set at exposition time from the database by the ``/metrics`` endpoint
rather than incremented on every transition: a gauge maintained from many
transactional code paths drifts on every rollback, while a scrape-time query
is always consistent with what an operator would see in the table.
"""

from prometheus_client import Counter, Gauge, Histogram

adapter_connect_success_total = Counter(
    "adapter_connect_success_total",
    "Successful protocol adapter connections.",
    ["device_id", "protocol"],
)

adapter_connect_failure_total = Counter(
    "adapter_connect_failure_total",
    "Failed protocol adapter connection attempts.",
    ["device_id", "protocol"],
)

adapter_read_latency_seconds = Histogram(
    "adapter_read_latency_seconds",
    "Latency of protocol adapter read() calls.",
    ["device_id", "protocol", "result"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

adapter_last_success_timestamp = Gauge(
    "adapter_last_success_timestamp",
    "Unix timestamp of the last successful adapter read, per device.",
    ["device_id", "protocol"],
)

telemetry_ingest_total = Counter(
    "telemetry_ingest_total",
    "Telemetry payloads accepted by the ingestion pipeline.",
)

telemetry_ingest_failed_total = Counter(
    "telemetry_ingest_failed_total",
    "Telemetry payloads rejected by the ingestion pipeline.",
    ["reason"],
)

telemetry_processing_latency_seconds = Histogram(
    "telemetry_processing_latency_seconds",
    "End-to-end latency of one telemetry ingestion attempt.",
    ["outcome"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

alarm_created_total = Counter(
    "alarm_created_total",
    "Alarm condition instances opened.",
    ["rule_id", "severity"],
)

alarm_cleared_total = Counter(
    "alarm_cleared_total",
    "Alarm condition instances cleared by an operator or by recovery.",
    ["rule_id", "severity"],
)

alarm_active_count = Gauge(
    "alarm_active_count",
    "Alarm instances currently in a non-CLEARED state, set at scrape time.",
)

incident_created_total = Counter(
    "incident_created_total",
    "Incidents created, by correlation or by the operator flow.",
)

incident_resolved_total = Counter(
    "incident_resolved_total",
    "Incidents that reached the RESOLVED status.",
)

incident_active_count = Gauge(
    "incident_active_count",
    "Incidents in a live status, set at scrape time.",
)

workflow_started_total = Counter(
    "workflow_started_total",
    "Decision workflow runs created.",
)

workflow_waiting_approval_total = Counter(
    "workflow_waiting_approval_total",
    "Workflow runs that reached the WAITING_APPROVAL human gate.",
)

workflow_failed_total = Counter(
    "workflow_failed_total",
    "Workflow runs that ended in the FAILED status.",
)

mqtt_reconnect_total = Counter(
    "mqtt_reconnect_total",
    "MQTT consumer reconnect attempts after a connection loss.",
)

background_task_failure_total = Counter(
    "background_task_failure_total",
    "Background asyncio tasks that ended with an unexpected exception.",
    ["task"],
)


def set_alarm_active_count(value: int) -> None:
    """Publish the scrape-time active-alarm gauge value."""

    alarm_active_count.set(value)


def set_incident_active_count(value: int) -> None:
    """Publish the scrape-time active-incident gauge value."""

    incident_active_count.set(value)
