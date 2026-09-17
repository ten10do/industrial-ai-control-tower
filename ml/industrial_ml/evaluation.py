"""One-shot evaluation of the frozen test split and error-analysis report generation."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from industrial_ml.dataset import DatasetArrays, load_dataset
from industrial_ml.metrics import (
    anomaly_metrics,
    classification_metrics,
    expected_calibration_error,
    multiclass_brier,
)
from industrial_ml.training import FAULT_CLASSES, robust_scores


def _anomaly_scores(bundle: dict[str, Any], features: np.ndarray) -> np.ndarray:
    if bundle["anomaly_kind"] == "isolation_forest":
        return np.asarray(-bundle["anomaly_model"].decision_function(features), dtype=float)
    indices = bundle["anomaly_feature_indices"]
    return robust_scores(
        features[:, indices],
        bundle["robust_center"],
        bundle["robust_scale"],
        int(bundle["anomaly_top_k"]),
    )


def detection_delays(
    dataset: DatasetArrays, mask: np.ndarray, anomaly_predictions: np.ndarray
) -> dict[str, Any]:
    scenario_ids = dataset.scenario_ids[mask]
    ticks = dataset.window_end_ticks[mask]
    starts = dataset.fault_start_ticks[mask]
    truth = dataset.y[mask]
    delays: list[int] = []
    missed: list[str] = []
    for scenario_id in sorted(set(scenario_ids.tolist())):
        rows = np.where(scenario_ids == scenario_id)[0]
        fault_rows = rows[truth[rows] != "NORMAL"]
        if not len(fault_rows):
            continue
        detected = [row for row in fault_rows if anomaly_predictions[row]]
        if detected:
            row = min(detected, key=lambda item: ticks[item])
            delays.append(max(0, int(ticks[row] - starts[row])))
        else:
            missed.append(str(scenario_id))
    return {
        "mean_ticks": float(np.mean(delays)) if delays else None,
        "median_ticks": float(np.median(delays)) if delays else None,
        "p95_ticks": float(np.percentile(delays, 95)) if delays else None,
        "detected_scenarios": len(delays),
        "missed_scenarios": missed,
    }


def analyze_errors(
    dataset: DatasetArrays,
    test_mask: np.ndarray,
    anomaly_predicted: np.ndarray,
    classifier_predicted: np.ndarray,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    truth = dataset.y[test_mask]
    scenarios = dataset.scenario_ids[test_mask]
    ticks = dataset.window_end_ticks[test_mask]
    severity = dataset.scenario_severity[test_mask]
    false_positive = np.where((truth == "NORMAL") & anomaly_predicted)[0]
    false_negative = np.where((truth != "NORMAL") & ~anomaly_predicted)[0]
    fault_rows = np.where(truth != "NORMAL")[0]
    confusions = fault_rows[classifier_predicted != truth[fault_rows]]
    low_severity = false_negative[severity[false_negative] < 0.70]
    scenario_meta = {item["scenario_id"]: item for item in manifest["scenarios"]}
    recovery_false_positive: list[int] = []
    for row in false_positive:
        spec = scenario_meta[str(scenarios[row])]
        recovery_end = spec["start_tick"] + 10 + spec["duration"] + 15
        if spec["fault_type"] != "NORMAL" and ticks[row] >= recovery_end:
            recovery_false_positive.append(int(row))

    def examples(rows: np.ndarray | list[int], limit: int = 12) -> list[dict[str, Any]]:
        return [
            {
                "scenario_id": str(scenarios[row]),
                "window_end_tick": int(ticks[row]),
                "truth": str(truth[row]),
            }
            for row in list(rows)[:limit]
        ]

    confusion_pairs: dict[str, int] = defaultdict(int)
    for row in confusions:
        confusion_pairs[f"{truth[row]} -> {classifier_predicted[row]}"] += 1
    sensor_rows = fault_rows[truth[fault_rows] == "SENSOR_FAILURE"]
    sensor_errors = sensor_rows[classifier_predicted[sensor_rows] != truth[sensor_rows]]
    return {
        "false_positive_count": int(len(false_positive)),
        "false_positive_examples": examples(false_positive),
        "false_negative_count": int(len(false_negative)),
        "false_negative_examples": examples(false_negative),
        "fault_confusion_count": int(len(confusions)),
        "fault_confusion_pairs": dict(sorted(confusion_pairs.items())),
        "low_severity_false_negative_count": int(len(low_severity)),
        "low_severity_examples": examples(low_severity),
        "recovery_false_positive_count": len(recovery_false_positive),
        "recovery_examples": examples(recovery_false_positive),
        "sensor_failure_confusion_count": int(len(sensor_errors)),
        "sensor_failure_examples": examples(sensor_errors),
    }


def evaluate(
    dataset: DatasetArrays, bundle: dict[str, Any], dataset_manifest: dict[str, Any]
) -> dict[str, Any]:
    test_mask = dataset.splits == "test"
    test_digest = hashlib.sha256()
    test_digest.update(np.ascontiguousarray(dataset.X[test_mask]).tobytes())
    test_digest.update(np.ascontiguousarray(dataset.y[test_mask]).tobytes())
    if test_digest.hexdigest() != dataset_manifest["frozen_test_sha256"]:
        raise RuntimeError("frozen test set hash mismatch")

    features = dataset.X[test_mask]
    truth = dataset.y[test_mask]
    scores = _anomaly_scores(bundle, features)
    anomaly = anomaly_metrics(truth, scores, float(bundle["anomaly_threshold"]))
    anomaly_predicted = scores >= float(bundle["anomaly_threshold"])

    fault_mask = truth != "NORMAL"
    fault_probabilities = bundle["classifier"].predict_proba(features[fault_mask])
    classifier_classes = bundle["classifier"].classes_
    fault_predicted = classifier_classes[fault_probabilities.argmax(axis=1)]
    classification = classification_metrics(truth[fault_mask], fault_predicted, FAULT_CLASSES)
    confidence = fault_probabilities.max(axis=1)
    uncertain = confidence < float(bundle["confidence_threshold"])
    calibration = {
        "method": "sigmoid calibration with scenario-group training folds",
        "brier": multiclass_brier(truth[fault_mask], fault_probabilities, classifier_classes),
        "ece": expected_calibration_error(
            truth[fault_mask], fault_probabilities, classifier_classes
        ),
        "uncertain_threshold": float(bundle["confidence_threshold"]),
        "uncertain_rate": float(np.mean(uncertain)),
    }

    all_classifier_predicted = np.full(len(truth), "NORMAL", dtype="U32")
    all_classifier_predicted[fault_mask] = fault_predicted
    errors = analyze_errors(
        dataset,
        test_mask,
        anomaly_predicted,
        all_classifier_predicted,
        dataset_manifest,
    )
    recalls = {name: float(classification["report"][name]["recall"]) for name in FAULT_CLASSES}
    acceptance = {
        "anomaly_pr_auc_gte_0_85": anomaly["pr_auc"] >= 0.85,
        "classification_macro_f1_gte_0_80": classification["macro_f1"] >= 0.80,
        "minimum_recall_gte_0_70": min(recalls.values()) >= 0.70,
        "normal_fpr_lte_0_05": anomaly["normal_false_positive_rate"] <= 0.05,
    }
    return {
        "test_windows": int(np.sum(test_mask)),
        "test_scenarios": len(set(dataset.scenario_ids[test_mask].tolist())),
        "frozen_test_sha256": dataset_manifest["frozen_test_sha256"],
        "anomaly": anomaly,
        "classification": classification,
        "per_class_recall": recalls,
        "calibration": calibration,
        "detection_delay": detection_delays(dataset, test_mask, anomaly_predicted),
        "error_analysis": errors,
        "acceptance": acceptance,
        "all_acceptance_targets_met": all(acceptance.values()),
    }


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "|" + "|".join("---" for _ in headers) + "|",
            *("| " + " | ".join(row) + " |" for row in rows),
        ]
    )


def write_reports(
    results: dict[str, Any], model_manifest: dict[str, Any], evaluation_path: Path, error_path: Path
) -> None:
    validation = model_manifest["validation_metrics"]
    anomaly = results["anomaly"]
    classification = results["classification"]
    report_rows = []
    for name, metrics in validation["classifier_candidates"].items():
        report_rows.append(
            [
                name,
                "fault classification",
                f"macro F1={metrics['macro_f1']:.4f}",
                "yes" if name == validation["selected_classifier"] else "no",
            ]
        )
    anomaly_rows = []
    for name, metrics in validation["anomaly_candidates"].items():
        anomaly_rows.append(
            [
                name,
                f"PR-AUC={metrics['pr_auc']:.4f}; F1={metrics['f1']:.4f}",
                "yes" if name == validation["selected_anomaly"] else "no",
            ]
        )
    classes = FAULT_CLASSES
    matrix = classification["confusion_matrix"]
    matrix_rows = [
        [classes[index], *(str(value) for value in row)] for index, row in enumerate(matrix)
    ]
    per_class_rows = [
        [
            name,
            f"{classification['report'][name]['precision']:.4f}",
            f"{classification['report'][name]['recall']:.4f}",
            f"{classification['report'][name]['f1-score']:.4f}",
        ]
        for name in classes
    ]
    content = f"""# Phase 3 Model Evaluation

## Scope and limitation

This is a **synthetic industrial motor diagnosis benchmark**. It proves the ML engineering
pipeline and performance on held-out simulator scenarios. It does not demonstrate equivalent
accuracy on real motors, sensors, environments, or failure mechanisms.

## Dataset and split

- Dataset: `{model_manifest["training_dataset_version"]}`
- Test scenarios: {results["test_scenarios"]}
- Test windows: {results["test_windows"]}
- Split unit: scenario and globally unique seed (no row-level random split)
- Frozen test hash: `{results["frozen_test_sha256"]}`
- Feature schema: `{model_manifest["feature_version"]}`, 76 features, 20-tick window, stride 5
- Forbidden label fields are excluded by the typed feature boundary and mandatory leakage test.

## Validation-only model selection

{_markdown_table(["Model", "Purpose", "Validation metric", "Selected"], report_rows)}

{_markdown_table(["Anomaly model", "Validation metrics", "Selected"], anomaly_rows)}

All thresholds, model selection, feature decisions, and confidence tuning used train/validation
only. This report is the single evaluation of the frozen test split.

## Final anomaly test metrics

- Precision: {anomaly["precision"]:.4f}
- Recall: {anomaly["recall"]:.4f}
- F1: {anomaly["f1"]:.4f}
- ROC-AUC: {anomaly["roc_auc"]:.4f}
- PR-AUC: {anomaly["pr_auc"]:.4f}
- Normal false-positive rate: {anomaly["normal_false_positive_rate"]:.4f}

## Final fault-classification test metrics

- Accuracy: {classification["accuracy"]:.4f}
- Balanced accuracy: {classification["balanced_accuracy"]:.4f}
- Macro F1: {classification["macro_f1"]:.4f}
- Weighted F1: {classification["weighted_f1"]:.4f}

{_markdown_table(["Class", "Precision", "Recall", "F1"], per_class_rows)}

## Confusion matrix

Rows are truth and columns are predictions.

{_markdown_table(["Truth", *classes], matrix_rows)}

The largest confusion pairs are recorded in `ERROR_ANALYSIS.md`, including the requested
BEARING_WEAR/MISALIGNMENT and OVERLOAD/OVERHEATING checks.

## Calibration and uncertainty

- Method: {results["calibration"]["method"]}
- Multiclass Brier score: {results["calibration"]["brier"]:.4f}
- Expected calibration error (10 bins): {results["calibration"]["ece"]:.4f}
- UNCERTAIN threshold: {results["calibration"]["uncertain_threshold"]:.4f}
- Test uncertainty rate: {results["calibration"]["uncertain_rate"]:.4f}

## Detection delay

- Mean: {results["detection_delay"]["mean_ticks"]} ticks
- Median: {results["detection_delay"]["median_ticks"]} ticks
- P95: {results["detection_delay"]["p95_ticks"]} ticks
- Detected scenarios: {results["detection_delay"]["detected_scenarios"]}
- Missed scenarios: {len(results["detection_delay"]["missed_scenarios"])}

## Acceptance targets

```json
{json.dumps(results["acceptance"], indent=2, sort_keys=True)}
```

Overall targets met: **{results["all_acceptance_targets_met"]}**

## Limitations

- Simulator labels describe synthetic injected scenarios, not verified real-world root causes.
- Faults are single-fault scenarios; concurrent faults are outside this benchmark.
- Sensor failure covers deterministic stuck/intermittent-spike behavior, not every sensor mode.
- Confidence calibration and thresholds require revalidation after domain or sensor changes.
- No LLM, RAG, agent workflow, or automated maintenance action participates in diagnosis.
"""
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    evaluation_path.write_text(content, encoding="utf-8")

    errors = results["error_analysis"]
    error_content = f"""# Phase 3 Error Analysis

This report intentionally records failures rather than filtering difficult windows.

## False positives

- Count: {errors["false_positive_count"]}
- Examples: `{json.dumps(errors["false_positive_examples"])}`

## False negatives

- Count: {errors["false_negative_count"]}
- Examples: `{json.dumps(errors["false_negative_examples"])}`

## Fault confusion

- Count: {errors["fault_confusion_count"]}
- Pairs: `{json.dumps(errors["fault_confusion_pairs"], sort_keys=True)}`

## Low-severity failures

- False negatives below scenario severity 0.70: {errors["low_severity_false_negative_count"]}
- Examples: `{json.dumps(errors["low_severity_examples"])}`

## Recovery phase

- Post-recovery false positives: {errors["recovery_false_positive_count"]}
- Examples: `{json.dumps(errors["recovery_examples"])}`

## Sensor failure edge cases

- Classification confusions: {errors["sensor_failure_confusion_count"]}
- Examples: `{json.dumps(errors["sensor_failure_examples"])}`

## Interpretation

Residual thermal/mechanical state after the injected label ends can legitimately remain abnormal;
these recovery false positives are retained. Low-severity ramps are the expected source of missed
early windows. Confusion pairs should be interpreted against overlapping simulated signal
patterns, not removed or relabeled after seeing test results.
"""
    error_path.write_text(error_content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the frozen Phase 3 test split once")
    parser.add_argument("--dataset", type=Path, default=Path("data/phase3_dataset.npz"))
    parser.add_argument(
        "--dataset-manifest", type=Path, default=Path("manifests/dataset_manifest.json")
    )
    parser.add_argument(
        "--artifact", type=Path, default=Path("../backend/artifacts/diagnosis-v1.joblib")
    )
    parser.add_argument(
        "--model-manifest", type=Path, default=Path("../backend/artifacts/model_manifest.json")
    )
    parser.add_argument("--json-output", type=Path, default=Path("output/test_evaluation.json"))
    parser.add_argument(
        "--report", type=Path, default=Path("../docs/evaluation/PHASE3_MODEL_EVALUATION.md")
    )
    parser.add_argument(
        "--error-report", type=Path, default=Path("../docs/evaluation/ERROR_ANALYSIS.md")
    )
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    dataset_manifest = json.loads(args.dataset_manifest.read_text(encoding="utf-8"))
    model_manifest = json.loads(args.model_manifest.read_text(encoding="utf-8"))
    artifact_digest = hashlib.sha256(args.artifact.read_bytes()).hexdigest()
    if artifact_digest != model_manifest["artifact_sha256"]:
        raise RuntimeError("artifact hash does not match model manifest")
    bundle = joblib.load(args.artifact)
    results = evaluate(dataset, bundle, dataset_manifest)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_reports(results, model_manifest, args.report, args.error_report)
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
