"""Evaluation metrics shared by training selection and frozen-test evaluation."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.preprocessing import label_binarize


def anomaly_metrics(labels: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, float]:
    truth = (labels != "NORMAL").astype(int)
    predicted = (scores >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        truth, predicted, average="binary", zero_division=0
    )
    normal_mask = truth == 0
    normal_count = int(np.sum(normal_mask))
    false_positive_count = int(np.sum(predicted[normal_mask]))
    false_positive_rate = false_positive_count / normal_count if normal_count else 0.0
    ci_lower, ci_upper = wilson_interval(false_positive_count, normal_count)
    return {
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "roc_auc": float(roc_auc_score(truth, scores)),
        "pr_auc": float(average_precision_score(truth, scores)),
        "normal_false_positive_rate": false_positive_rate,
        "normal_false_positive_count": float(false_positive_count),
        "normal_window_count": float(normal_count),
        "normal_fpr_ci95_lower": ci_lower,
        "normal_fpr_ci95_upper": ci_upper,
    }


def wilson_interval(
    successes: int, total: int, z: float = 1.959963984540054
) -> tuple[float, float]:
    """Return the two-sided Wilson score interval for a binomial proportion."""
    if total <= 0:
        return 0.0, 0.0
    proportion = successes / total
    denominator = 1.0 + z**2 / total
    center = (proportion + z**2 / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1.0 - proportion) / total + z**2 / (4.0 * total**2))
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def classification_metrics(
    truth: np.ndarray, predicted: np.ndarray, classes: list[str]
) -> dict[str, Any]:
    return {
        "accuracy": float(accuracy_score(truth, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(truth, predicted)),
        "macro_f1": float(f1_score(truth, predicted, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(truth, predicted, average="weighted", zero_division=0)),
        "report": classification_report(
            truth, predicted, labels=classes, output_dict=True, zero_division=0
        ),
        "confusion_matrix": confusion_matrix(truth, predicted, labels=classes).tolist(),
    }


def multiclass_brier(truth: np.ndarray, probabilities: np.ndarray, classes: np.ndarray) -> float:
    encoded = label_binarize(truth, classes=classes)
    if encoded.shape[1] == 1 and len(classes) == 2:
        encoded = np.column_stack((1 - encoded, encoded))
    return float(np.mean(np.sum((probabilities - encoded) ** 2, axis=1)))


def expected_calibration_error(
    truth: np.ndarray, probabilities: np.ndarray, classes: np.ndarray, bins: int = 10
) -> float:
    confidence = probabilities.max(axis=1)
    predicted = classes[probabilities.argmax(axis=1)]
    correct = (predicted == truth).astype(float)
    error = 0.0
    edges = np.linspace(0.0, 1.0, bins + 1)
    for lower, upper in zip(edges[:-1], edges[1:], strict=True):
        mask = (confidence > lower) & (confidence <= upper)
        if np.any(mask):
            error += float(np.mean(mask)) * abs(
                float(np.mean(correct[mask]) - np.mean(confidence[mask]))
            )
    return error
