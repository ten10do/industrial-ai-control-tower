"""Metric computation for the Agent Observability layer.

This module is deliberately free of database access so the statistics can be
verified with synthetic samples. ``repository.py`` produces the raw aggregate
values and the functions here derive the reported metrics from them.

Token accounting is honest by construction. When a provider does not return
usage information the stored token columns are ``NULL``; the aggregate then
reports ``None`` together with a ``steps_with_token_data`` count rather than a
fabricated zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.observability.models import (
    AgentBreakdownRead,
    ObservabilityMetricsRead,
    TokenUsageRead,
)


@dataclass(frozen=True)
class RunCounters:
    """Raw run counters grouped by lifecycle status."""

    total_runs: int = 0
    runs_running: int = 0
    runs_waiting_approval: int = 0
    runs_today: int = 0
    success_count: int = 0
    failure_count: int = 0
    blocked_count: int = 0
    cancelled_count: int = 0


@dataclass(frozen=True)
class RunLatency:
    """Whole-run latency: an exact average plus a bounded sample for percentiles."""

    avg_ms: float | None = None
    samples_ms: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class StepLatency:
    """Agent-step latency average."""

    avg_ms: float | None = None


@dataclass(frozen=True)
class TokenTotals:
    """Raw token accounting across all stored steps."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    steps_with_token_data: int = 0
    steps_total: int = 0


@dataclass(frozen=True)
class AgentAggregate:
    """Raw per-agent aggregate."""

    agent_name: str
    steps_total: int = 0
    failures: int = 0
    latency_sum_ms: float = 0.0
    latency_count: int = 0
    latency_samples_ms: list[float] = field(default_factory=list)
    total_tokens: int | None = None
    schema_retries: int | None = None


@dataclass(frozen=True)
class RawObservabilityStats:
    """Everything the repository measured, before derivation."""

    counters: RunCounters = field(default_factory=RunCounters)
    run_latency: RunLatency = field(default_factory=RunLatency)
    step_latency: StepLatency = field(default_factory=StepLatency)
    tokens: TokenTotals = field(default_factory=TokenTotals)
    step_status_counts: dict[str, int] = field(default_factory=dict)
    by_agent: list[AgentAggregate] = field(default_factory=list)


def mean(values: list[float]) -> float | None:
    """Return the arithmetic mean, or ``None`` for an empty sample."""
    if not values:
        return None
    return sum(values) / len(values)


def percentile(values: list[float], fraction: float) -> float | None:
    """Return the nearest-rank percentile of ``values``.

    ``fraction`` is a value in ``[0, 1]``. The sample set is small and fully
    materialised, so nearest-rank is used rather than an interpolated estimate.
    """
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def build_metrics(raw: RawObservabilityStats) -> ObservabilityMetricsRead:
    """Derive the reported observability metrics from raw aggregates."""
    counters = raw.counters
    completed = (
        counters.success_count
        + counters.failure_count
        + counters.blocked_count
        + counters.cancelled_count
    )
    tokens = raw.tokens
    by_agent = [
        AgentBreakdownRead(
            agent_name=item.agent_name,
            steps_total=item.steps_total,
            failures=item.failures,
            avg_latency_ms=(
                item.latency_sum_ms / item.latency_count if item.latency_count else None
            ),
            p95_latency_ms=percentile(item.latency_samples_ms, 0.95),
            total_tokens=item.total_tokens,
            schema_retries=item.schema_retries,
        )
        for item in raw.by_agent
    ]
    return ObservabilityMetricsRead(
        total_runs=counters.total_runs,
        runs_running=counters.runs_running,
        runs_waiting_approval=counters.runs_waiting_approval,
        runs_today=counters.runs_today,
        completed_runs=completed,
        success_count=counters.success_count,
        failure_count=counters.failure_count,
        blocked_count=counters.blocked_count,
        cancelled_count=counters.cancelled_count,
        success_rate=None if completed == 0 else counters.success_count / completed,
        avg_latency_ms=raw.run_latency.avg_ms,
        p95_latency_ms=percentile(raw.run_latency.samples_ms, 0.95),
        avg_step_latency_ms=raw.step_latency.avg_ms,
        step_status_counts=dict(raw.step_status_counts),
        token_usage=TokenUsageRead(
            input_tokens=tokens.input_tokens,
            output_tokens=tokens.output_tokens,
            total_tokens=tokens.total_tokens,
            steps_with_token_data=tokens.steps_with_token_data,
            steps_total=tokens.steps_total,
        ),
        by_agent=by_agent,
    )
