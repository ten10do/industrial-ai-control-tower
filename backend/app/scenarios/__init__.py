"""Industrial scenario validation orchestration.

This package evaluates the production services. It does not implement a second
alarm, incident, diagnosis, workflow, or work-order domain.
"""

from app.scenarios.contracts import ScenarioDefinition, ScenarioResult
from app.scenarios.metrics import EvaluationMetrics, compute_metrics

__all__ = ["EvaluationMetrics", "ScenarioDefinition", "ScenarioResult", "compute_metrics"]
