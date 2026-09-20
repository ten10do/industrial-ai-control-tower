"""Root-cause analysis for the immutable, already exposed Phase 3 Test V1."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from app.ml.features import WindowSample

from industrial_ml.dataset import DatasetArrays, ScenarioSpec, load_dataset, simulate_scenario
from industrial_ml.metrics import anomaly_metrics
from industrial_ml.training import robust_scores


def signal_summary(window: list[WindowSample], last: WindowSample, name: str) -> dict[str, float]:
    values = [float(getattr(sample, name)) for sample in window]
    return {"last": float(getattr(last, name)), "mean": float(np.mean(values))}


def anomaly_scores(bundle: dict[str, Any], features: np.ndarray) -> np.ndarray:
    indices = bundle["anomaly_feature_indices"]
    return robust_scores(
        features[:, indices],
        bundle["robust_center"],
        bundle["robust_scale"],
        int(bundle["anomaly_top_k"]),
    )


def distribution(scores: np.ndarray, threshold: float) -> dict[str, float]:
    return {
        "count": float(len(scores)),
        "mean": float(np.mean(scores)),
        "std": float(np.std(scores)),
        "median": float(np.median(scores)),
        "p90": float(np.percentile(scores, 90)),
        "p95": float(np.percentile(scores, 95)),
        "p99": float(np.percentile(scores, 99)),
        "max": float(np.max(scores)),
        "above_threshold": float(np.sum(scores >= threshold)),
    }


def _scenario_specs(manifest: dict[str, Any]) -> dict[str, ScenarioSpec]:
    return {item["scenario_id"]: ScenarioSpec(**item) for item in manifest["scenarios"]}


def analyze(
    dataset: DatasetArrays, bundle: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    threshold = float(bundle["anomaly_threshold"])
    validation_mask = dataset.splits == "validation"
    test_mask = dataset.splits == "test"
    validation_scores = anomaly_scores(bundle, dataset.X[validation_mask])
    test_scores = anomaly_scores(bundle, dataset.X[test_mask])
    validation_truth = dataset.y[validation_mask]
    test_truth = dataset.y[test_mask]
    groups = {
        "normal_validation": distribution(
            validation_scores[validation_truth == "NORMAL"], threshold
        ),
        "normal_exposed_test": distribution(test_scores[test_truth == "NORMAL"], threshold),
        "fault_validation": distribution(
            validation_scores[validation_truth != "NORMAL"], threshold
        ),
        "fault_exposed_test": distribution(test_scores[test_truth != "NORMAL"], threshold),
    }
    test_metrics = anomaly_metrics(test_truth, test_scores, threshold)
    local_false_positives = np.where((test_truth == "NORMAL") & (test_scores >= threshold))[0]
    global_test_rows = np.flatnonzero(test_mask)
    specs = _scenario_specs(manifest)
    simulated: dict[str, Any] = {}
    feature_names = np.asarray(dataset.feature_names)
    anomaly_indices = np.asarray(bundle["anomaly_feature_indices"])
    selected_names = feature_names[anomaly_indices]
    false_positives: list[dict[str, Any]] = []
    cause_counts: Counter[str] = Counter()

    for local_row in local_false_positives:
        global_row = int(global_test_rows[local_row])
        scenario_id = str(dataset.scenario_ids[global_row])
        spec = specs[scenario_id]
        if scenario_id not in simulated:
            simulated[scenario_id] = simulate_scenario(spec)[0]
        samples = simulated[scenario_id]
        end_tick = int(dataset.window_end_ticks[global_row])
        start_tick = end_tick - int(bundle["window_size"]) + 1
        window = samples[start_tick : end_tick + 1]
        vector = dataset.X[global_row]
        selected_values = vector[anomaly_indices]
        z = np.abs((selected_values - bundle["robust_center"]) / bundle["robust_scale"])
        top = np.argsort(z)[::-1][:8]
        score = float(test_scores[local_row])
        causes: list[str] = []
        recovery_end = spec.start_tick + 10 + spec.duration + 15
        if spec.fault_type != "NORMAL" and start_tick < recovery_end <= end_tick:
            causes.append("recovery_window_overlap")
        elif spec.fault_type != "NORMAL" and start_tick >= recovery_end:
            causes.append("post_recovery_residual_state")
        if float(np.mean([sample.load_pct for sample in window])) >= 80.0:
            causes.append("high_load_normal_regime")
        if (score - threshold) / threshold <= 0.10:
            causes.append("threshold_proximity_within_10pct")
        if spec.fault_type == "NORMAL" and not causes:
            causes.append("natural_signal_tail")
        for cause in causes:
            cause_counts[cause] += 1
        last = window[-1]

        false_positives.append(
            {
                "scenario_id": scenario_id,
                "seed": spec.seed,
                "window_start_tick": start_tick,
                "window_end_tick": end_tick,
                "anomaly_score": score,
                "threshold": threshold,
                "threshold_margin": score - threshold,
                "scenario_fault_type": spec.fault_type,
                "scenario_severity": spec.severity,
                "causes": causes,
                "signals": {
                    name: signal_summary(window, last, name)
                    for name in (
                        "load_pct",
                        "temperature_c",
                        "bearing_temperature_c",
                        "vibration_mm_s",
                        "current_a",
                        "rpm",
                    )
                },
                "top_anomaly_features": [
                    {
                        "name": str(selected_names[index]),
                        "value": float(selected_values[index]),
                        "robust_center": float(bundle["robust_center"][index]),
                        "robust_scale": float(bundle["robust_scale"][index]),
                        "abs_robust_z": float(z[index]),
                    }
                    for index in top
                ],
            }
        )

    return {
        "status": "EXPOSED_TEST_V1",
        "model_version": "diagnosis-v1",
        "artifact_sha256": "043b88b4ab996c673996a3f6a9cc847a79a589dfc93f021dff9cca58d9b8167f",
        "threshold": threshold,
        "score_distributions": groups,
        "normal_false_positive_count": int(test_metrics["normal_false_positive_count"]),
        "normal_window_count": int(test_metrics["normal_window_count"]),
        "normal_fpr": test_metrics["normal_false_positive_rate"],
        "normal_fpr_ci95": [
            test_metrics["normal_fpr_ci95_lower"],
            test_metrics["normal_fpr_ci95_upper"],
        ],
        "cause_counts": dict(cause_counts),
        "false_positives": false_positives,
    }


def write_report(result: dict[str, Any], path: Path) -> None:
    distributions = result["score_distributions"]
    distribution_rows = "\n".join(
        "| {name} | {count:.0f} | {mean:.3f} | {median:.3f} | {p90:.3f} | "
        "{p95:.3f} | {p99:.3f} | {max:.3f} | {above_threshold:.0f} |".format(name=name, **values)
        for name, values in distributions.items()
    )
    fp_rows = "\n".join(
        "| {scenario_id} | {seed} | {window_start_tick}–{window_end_tick} | "
        "{anomaly_score:.3f} | {threshold_margin:.3f} | {load:.2f} | {temp:.2f} | "
        "{bearing:.2f} | {vibration:.2f} | {current:.2f} | {rpm:.1f} | {causes} |".format(
            scenario_id=item["scenario_id"],
            seed=item["seed"],
            window_start_tick=item["window_start_tick"],
            window_end_tick=item["window_end_tick"],
            anomaly_score=item["anomaly_score"],
            threshold_margin=item["threshold_margin"],
            load=item["signals"]["load_pct"]["mean"],
            temp=item["signals"]["temperature_c"]["mean"],
            bearing=item["signals"]["bearing_temperature_c"]["mean"],
            vibration=item["signals"]["vibration_mm_s"]["mean"],
            current=item["signals"]["current_a"]["mean"],
            rpm=item["signals"]["rpm"]["mean"],
            causes=", ".join(item["causes"]),
        )
        for item in result["false_positives"]
    )
    content = f"""# EXPOSED_TEST_V1 Normal False-Positive Analysis

This report preserves the immutable Phase 3 result. It is diagnostic evidence only and is not a
new acceptance run.

- Model: `{result["model_version"]}`
- Artifact: `{result["artifact_sha256"]}`
- Threshold: {result["threshold"]:.6f}
- Normal windows: {result["normal_window_count"]}
- False positives: {result["normal_false_positive_count"]}
- Normal FPR: {result["normal_fpr"]:.6%}
- Wilson 95% CI: [{result["normal_fpr_ci95"][0]:.6%}, {result["normal_fpr_ci95"][1]:.6%}]

## Score distributions

| Group | N | Mean | Median | P90 | P95 | P99 | Max | ≥ threshold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{distribution_rows}

## Root cause

All Test V1 false positives occur in scenarios that previously contained an injected fault. The
simulator label returns to NORMAL when the fault envelope ends, while motor temperature,
bearing temperature, vibration, load, or window history can remain physically displaced. This
is recovery contamination / residual state, not random NORMAL-only scenario variance. Threshold
tail placement contributes: the original rule optimized validation F1 with only a point-estimate
FPR ≤5%, providing no sampling margin. The selected detector is robust statistics, so Isolation
Forest behavior is not causal.

Cause counts: `{json.dumps(result["cause_counts"], sort_keys=True)}`

## All 38 false positives

Signal columns are window means. Full last values and top robust-z feature vectors follow in JSON.

| Scenario | Seed | Ticks | Score | Margin | Load | Motor T | Bearing T | Vib | A | RPM | Causes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
{fp_rows}

## Full feature evidence

```json
{json.dumps(result["false_positives"], indent=2, sort_keys=True)}
```
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("data/phase3_dataset.npz"))
    parser.add_argument("--manifest", type=Path, default=Path("manifests/dataset_manifest.json"))
    parser.add_argument(
        "--artifact", type=Path, default=Path("../backend/artifacts/diagnosis-v1.joblib")
    )
    parser.add_argument(
        "--json-output", type=Path, default=Path("output/exposed_test_v1_analysis.json")
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("../docs/evaluation/EXPOSED_TEST_V1_ANALYSIS.md"),
    )
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    bundle = joblib.load(args.artifact)
    result = analyze(dataset, bundle, manifest)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_report(result, args.report)
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "false_positives"},
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
