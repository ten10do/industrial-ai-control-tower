"""One-shot acceptance evaluation for the frozen Phase 3.1 blind holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib

from industrial_ml.blind import BLIND_DATASET_VERSION
from industrial_ml.dataset import load_dataset
from industrial_ml.evaluation import evaluate


def _table(headers: list[str], rows: list[list[str]]) -> str:
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "|" + "|".join("---" for _ in headers) + "|",
            *("| " + " | ".join(row) + " |" for row in rows),
        ]
    )


def write_blind_reports(
    results: dict[str, Any],
    model_manifest: dict[str, Any],
    blind_manifest: dict[str, Any],
    report_path: Path,
    error_path: Path,
) -> None:
    anomaly = results["anomaly"]
    classification = results["classification"]
    validation_anomaly = model_manifest["validation_metrics"]["anomaly_candidates"][
        "robust_statistical"
    ]
    blind_scenarios = blind_manifest["scenario_count"]
    blind_normal_scenarios = blind_manifest["normal_scenario_count"]
    fpr_ci_lower = anomaly["normal_fpr_ci95_lower"]
    fpr_ci_upper = anomaly["normal_fpr_ci95_upper"]
    classes = list(results["per_class_recall"])
    class_rows = [
        [
            label,
            f"{classification['report'][label]['precision']:.4f}",
            f"{classification['report'][label]['recall']:.4f}",
            f"{classification['report'][label]['f1-score']:.4f}",
        ]
        for label in classes
    ]
    matrix_rows = [
        [label, *(str(value) for value in row)]
        for label, row in zip(classes, classification["confusion_matrix"], strict=True)
    ]
    content = f"""# Phase 3.1 Blind Holdout Evaluation

## Acceptance protocol

This is the first and only label-based evaluation of the frozen blind holdout. Its 120 seeds were
allocated before `diagnosis-v1.1` was trained. The model and threshold were fixed from the original
train/validation splits, then committed with the blind manifest hash before this run.

`EXPOSED_TEST_V1` remains historical evidence: Normal FPR **5.1842% (38/733)**. It was not
overwritten and was not used as the acceptance set for this version.

## Identity

- Model version: `{model_manifest["model_version"]}`
- Parent model: `{model_manifest["parent_model_version"]}`
- Artifact SHA-256: `{model_manifest["artifact_sha256"]}`
- Feature version: `{model_manifest["feature_version"]}`
- Training dataset: `{model_manifest["training_dataset_version"]}`
- Blind dataset: `{blind_manifest["dataset_version"]}`
- Blind scenarios: {blind_scenarios} total; {blind_normal_scenarios} NORMAL
- Blind manifest SHA-256: `{blind_manifest["manifest_sha256"]}`
- Blind holdout SHA-256: `{blind_manifest["blind_holdout_sha256"]}`
- New seed overlap: {blind_manifest["new_seed_verification"]["overlap_count"]}

## Validation-only operating point

- Algorithm: {model_manifest["threshold_selection"]["algorithm"]}
- Old threshold: 45.887684
- New threshold: {model_manifest["thresholds"]["anomaly"]:.6f}
- Validation Normal FPR: {validation_anomaly["normal_false_positive_rate"]:.6%}
- Validation FPR Wilson 95% upper: {validation_anomaly["normal_fpr_ci95_upper"]:.6%}
- Validation anomaly recall: {validation_anomaly["recall"]:.6f}

## Blind anomaly metrics

- PR-AUC: {anomaly["pr_auc"]:.6f}
- ROC-AUC: {anomaly["roc_auc"]:.6f}
- Precision: {anomaly["precision"]:.6f}
- Recall: {anomaly["recall"]:.6f}
- F1: {anomaly["f1"]:.6f}
- Normal false positives: {int(anomaly["normal_false_positive_count"])}
- Normal windows: {int(anomaly["normal_window_count"])}
- Normal FPR: {anomaly["normal_false_positive_rate"]:.6%}
- Normal FPR Wilson 95% CI: [{fpr_ci_lower:.6%}, {fpr_ci_upper:.6%}]

## Blind fault classification

- Accuracy: {classification["accuracy"]:.6f}
- Balanced accuracy: {classification["balanced_accuracy"]:.6f}
- Macro F1: {classification["macro_f1"]:.6f}
- Weighted F1: {classification["weighted_f1"]:.6f}
- Minimum per-class recall: {min(results["per_class_recall"].values()):.6f}

{_table(["Class", "Precision", "Recall", "F1"], class_rows)}

## Confusion matrix

{_table(["Truth", *classes], matrix_rows)}

## Detection delay

- Mean: {results["detection_delay"]["mean_ticks"]} ticks
- Median: {results["detection_delay"]["median_ticks"]} ticks
- P95: {results["detection_delay"]["p95_ticks"]} ticks
- Detected scenarios: {results["detection_delay"]["detected_scenarios"]}
- Missed scenarios: {len(results["detection_delay"]["missed_scenarios"])}

## Acceptance

```json
{json.dumps(results["acceptance"], indent=2, sort_keys=True)}
```

Overall: **{"PASS" if results["all_acceptance_targets_met"] else "PARTIAL"}**

## Interpretation

This remains a synthetic benchmark. Class-specific simulator templates can make classification
substantially easier than real diagnosis. The blind set widens load, severity, timing, ramp, and
recovery ranges, but it does not establish real-world generalization.
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content, encoding="utf-8")

    errors = results["error_analysis"]
    error_content = f"""# Phase 3.1 Blind Error Analysis

- False positives: {errors["false_positive_count"]}
- False negatives: {errors["false_negative_count"]}
- Fault confusions: {errors["fault_confusion_count"]}
- Low-severity false negatives: {errors["low_severity_false_negative_count"]}
- Recovery false positives: {errors["recovery_false_positive_count"]}
- Sensor-failure confusions: {errors["sensor_failure_confusion_count"]}

## Confusion pairs

```json
{json.dumps(errors["fault_confusion_pairs"], indent=2, sort_keys=True)}
```

## Examples

```json
{json.dumps(errors, indent=2, sort_keys=True)}
```
"""
    error_path.write_text(error_content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("data/phase3_blind_holdout_v1.npz"))
    parser.add_argument(
        "--blind-manifest", type=Path, default=Path("manifests/blind_holdout_manifest_v1.json")
    )
    parser.add_argument(
        "--artifact", type=Path, default=Path("../backend/artifacts/diagnosis-v1.1.joblib")
    )
    parser.add_argument(
        "--model-manifest",
        type=Path,
        default=Path("../backend/artifacts/model_manifest-v1.1.json"),
    )
    parser.add_argument("--json-output", type=Path, default=Path("output/blind_evaluation_v1.json"))
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("../docs/evaluation/PHASE3_1_BLIND_EVALUATION.md"),
    )
    parser.add_argument(
        "--error-report",
        type=Path,
        default=Path("../docs/evaluation/PHASE3_1_ERROR_ANALYSIS.md"),
    )
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    blind_manifest = json.loads(args.blind_manifest.read_text(encoding="utf-8"))
    model_manifest = json.loads(args.model_manifest.read_text(encoding="utf-8"))
    if blind_manifest["dataset_version"] != BLIND_DATASET_VERSION:
        raise RuntimeError("unexpected blind dataset version")
    if model_manifest["blind_acceptance_manifest_sha256"] != blind_manifest["manifest_sha256"]:
        raise RuntimeError("model was not frozen against this blind manifest")
    artifact_sha = hashlib.sha256(args.artifact.read_bytes()).hexdigest()
    if artifact_sha != model_manifest["artifact_sha256"]:
        raise RuntimeError("artifact hash mismatch")
    bundle = joblib.load(args.artifact)
    results = evaluate(dataset, bundle, blind_manifest, split_name="blind")
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_blind_reports(results, model_manifest, blind_manifest, args.report, args.error_report)
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
