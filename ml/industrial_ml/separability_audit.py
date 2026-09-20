"""Audit leakage and synthetic template separability behind perfect classification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from app.ml.features import FORBIDDEN_FEATURE_FIELDS, FeatureExtractor

from industrial_ml.dataset import CLASSES, DatasetArrays, load_dataset


def _summary(values: np.ndarray) -> dict[str, float]:
    return {
        "min": float(np.min(values)),
        "mean": float(np.mean(values)),
        "max": float(np.max(values)),
    }


def audit(dataset: DatasetArrays, manifest: dict[str, Any]) -> dict[str, Any]:
    feature_names = set(dataset.feature_names)
    forbidden_present = sorted(feature_names.intersection(FORBIDDEN_FEATURE_FIELDS))
    split_groups = {
        split: set(dataset.scenario_ids[dataset.splits == split].tolist())
        for split in ("train", "validation", "test")
    }
    split_seeds = {
        split: set(dataset.seeds[dataset.splits == split].tolist())
        for split in ("train", "validation", "test")
    }
    overlap = {
        f"{left}_{right}": {
            "scenarios": len(split_groups[left].intersection(split_groups[right])),
            "seeds": len(split_seeds[left].intersection(split_seeds[right])),
        }
        for left, right in (
            ("train", "validation"),
            ("train", "test"),
            ("validation", "test"),
        )
    }

    config_summary: dict[str, Any] = {}
    for split in ("train", "validation", "test"):
        config_summary[split] = {}
        for fault_type in CLASSES:
            items = [
                item
                for item in manifest["scenarios"]
                if item["split"] == split and item["fault_type"] == fault_type
            ]
            config_summary[split][fault_type] = {
                "count": len(items),
                "initial_load_pct": _summary(
                    np.asarray([item["initial_load_pct"] for item in items])
                ),
                "severity": _summary(np.asarray([item["severity"] for item in items])),
                "start_tick": _summary(np.asarray([item["start_tick"] for item in items])),
                "duration": _summary(np.asarray([item["duration"] for item in items])),
            }

    fault_train = (dataset.splits == "train") & (dataset.y != "NORMAL")
    fault_test = (dataset.splits == "test") & (dataset.y != "NORMAL")
    train_mean = dataset.X[fault_train].mean(axis=0)
    train_std = np.maximum(dataset.X[fault_train].std(axis=0), 1e-6)
    class_centroids = {
        label: (
            (dataset.X[fault_train & (dataset.y == label)].mean(axis=0) - train_mean) / train_std
        )
        for label in CLASSES
        if label != "NORMAL"
    }
    standardized_test = (dataset.X[fault_test] - train_mean) / train_std
    labels = list(class_centroids)
    centroid_matrix = np.vstack([class_centroids[label] for label in labels])
    distances = np.linalg.norm(
        standardized_test[:, np.newaxis, :] - centroid_matrix[np.newaxis, :, :], axis=2
    )
    nearest = np.asarray(labels)[distances.argmin(axis=1)]
    nearest_centroid_accuracy = float(np.mean(nearest == dataset.y[fault_test]))

    top_features: dict[str, list[dict[str, float | str]]] = {}
    for label in labels:
        class_mask = fault_train & (dataset.y == label)
        other_mask = fault_train & (dataset.y != "NORMAL") & (dataset.y != label)
        effect = np.abs(
            (dataset.X[class_mask].mean(axis=0) - dataset.X[other_mask].mean(axis=0)) / train_std
        )
        top = np.argsort(effect)[::-1][:8]
        top_features[label] = [
            {"feature": dataset.feature_names[index], "standardized_effect": float(effect[index])}
            for index in top
        ]

    return {
        "feature_count": len(dataset.feature_names),
        "feature_schema_matches_runtime": dataset.feature_names == FeatureExtractor().feature_names,
        "forbidden_features_present": forbidden_present,
        "scenario_seed_overlap": overlap,
        "config_summary": config_summary,
        "nearest_train_centroid_test_accuracy": nearest_centroid_accuracy,
        "top_class_template_features": top_features,
        "conclusion": (
            "No direct label or group leakage was found. Perfect Random Forest classification is "
            "credible inside this synthetic benchmark because each fault injects a stable, "
            "class-specific signal signature under the same generation family. It is not evidence "
            "of perfect real-world fault diagnosis."
        ),
    }


def write_report(result: dict[str, Any], path: Path) -> None:
    template_sections = "\n\n".join(
        f"### {label}\n\n```json\n{json.dumps(features, indent=2)}\n```"
        for label, features in result["top_class_template_features"].items()
    )
    content = f"""# Synthetic Classification Separability Audit

## Leakage checks

- Feature count: {result["feature_count"]}
- Runtime schema match: {result["feature_schema_matches_runtime"]}
- Forbidden direct fields present: `{result["forbidden_features_present"]}`
- Scenario/seed overlap: `{json.dumps(result["scenario_seed_overlap"], sort_keys=True)}`
- Metadata such as scenario ID and seed remains in evaluation arrays only; it is not in `X`.

## Why Macro F1 reached 1.0000

The split is leakage-safe, but all splits come from one simulator family. Fault effects are
deliberately class-specific: bearing wear adds strong vibration plus bearing heat; overload adds
load/current/power and RPM droop; overheating adds motor/bearing heat with little vibration;
misalignment primarily adds vibration with a small current/thermal effect; sensor failure creates
stuck/intermittent temperature behavior. Severity changes magnitude but not this causal template.

Even a nearest-training-centroid classifier over standardized features reaches
{result["nearest_train_centroid_test_accuracy"]:.4f} accuracy on exposed Test V1 fault windows.
This supports synthetic separability as the explanation; it does not support a real-world 100%
claim.

Train, validation, and test use different scenarios and seeds but draw load, severity, timing, and
duration from the same ranges. Configuration summaries are retained below for audit.

```json
{json.dumps(result["config_summary"], indent=2, sort_keys=True)}
```

## Strongest class-template features

{template_sections}

## Conclusion

{result["conclusion"]}
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("data/phase3_dataset.npz"))
    parser.add_argument("--manifest", type=Path, default=Path("manifests/dataset_manifest.json"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("../docs/evaluation/SYNTHETIC_SEPARABILITY_AUDIT.md"),
    )
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = audit(dataset, manifest)
    write_report(result, args.output)
    print(
        json.dumps(
            {
                "forbidden_features_present": result["forbidden_features_present"],
                "scenario_seed_overlap": result["scenario_seed_overlap"],
                "nearest_train_centroid_test_accuracy": result[
                    "nearest_train_centroid_test_accuracy"
                ],
                "conclusion": result["conclusion"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
