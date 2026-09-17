"""Train baselines, select on validation only, calibrate, and freeze an artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
from app.ml.features import FEATURE_VERSION, SIGNALS
from app.ml.runtime import MODEL_VERSION
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

from industrial_ml.dataset import (
    CLASSES,
    DATASET_VERSION,
    DatasetArrays,
    content_hash,
    load_dataset,
)
from industrial_ml.metrics import (
    anomaly_metrics,
    classification_metrics,
    expected_calibration_error,
    multiclass_brier,
)

RANDOM_SEED = 20260917
FAULT_CLASSES = [name for name in CLASSES if name != "NORMAL"]
ANOMALY_SUFFIXES = ("__mean", "__max", "__min", "__median", "__range", "__std")


def _git_sha(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def robust_parameters(normal_features: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    center = np.median(normal_features, axis=0)
    mad = np.median(np.abs(normal_features - center), axis=0)
    scale = np.maximum(mad * 1.4826, np.std(normal_features, axis=0) * 0.1)
    return center, np.maximum(scale, 1e-6)


def robust_scores(
    features: np.ndarray, center: np.ndarray, scale: np.ndarray, top_k: int = 1
) -> np.ndarray:
    z = np.abs((features - center) / scale)
    return np.asarray(np.mean(np.partition(z, -top_k, axis=1)[:, -top_k:], axis=1), dtype=float)


def choose_anomaly_threshold(labels: np.ndarray, scores: np.ndarray) -> float:
    candidates = np.unique(np.quantile(scores, np.linspace(0.02, 0.98, 150)))
    eligible: list[tuple[float, float]] = []
    all_results: list[tuple[float, float, float]] = []
    for threshold in candidates:
        metrics = anomaly_metrics(labels, scores, float(threshold))
        all_results.append(
            (metrics["f1"], -metrics["normal_false_positive_rate"], float(threshold))
        )
        if metrics["normal_false_positive_rate"] <= 0.05:
            eligible.append((metrics["f1"], float(threshold)))
    if eligible:
        return max(eligible)[1]
    return max(all_results)[2]


def deterministic_rule_predict(features: np.ndarray, feature_names: tuple[str, ...]) -> np.ndarray:
    index = {name: position for position, name in enumerate(feature_names)}
    predictions: list[str] = []
    for row in features:
        temperature = row[index["temperature_c__max"]]
        bearing = row[index["bearing_temperature_c__max"]]
        vibration = row[index["vibration_mm_s__max"]]
        load = row[index["load_pct__mean"]]
        temp_range = row[index["temperature_c__range"]]
        if temp_range > 14 and bearing < temperature - 5:
            predictions.append("SENSOR_FAILURE")
        elif load > 75:
            predictions.append("OVERLOAD")
        elif temperature > 75 and bearing > 65 and vibration < 5:
            predictions.append("OVERHEATING")
        elif vibration > 7 and bearing > 60:
            predictions.append("BEARING_WEAR")
        else:
            predictions.append("MISALIGNMENT")
    return np.asarray(predictions)


def choose_confidence_threshold(
    truth: np.ndarray, probabilities: np.ndarray, classes: np.ndarray
) -> float:
    confidence = probabilities.max(axis=1)
    predicted = classes[probabilities.argmax(axis=1)]
    choices: list[tuple[float, float]] = []
    for threshold in np.arange(0.45, 0.91, 0.025):
        accepted = confidence >= threshold
        coverage = float(np.mean(accepted))
        if coverage < 0.60:
            continue
        accuracy = float(np.mean(predicted[accepted] == truth[accepted]))
        choices.append((accuracy - 0.1 * (1.0 - coverage), float(threshold)))
    return max(choices)[1] if choices else 0.65


def _normal_signal_stats(
    dataset: DatasetArrays, train_mask: np.ndarray
) -> dict[str, dict[str, float]]:
    names = {name: index for index, name in enumerate(dataset.feature_names)}
    normal = train_mask & (dataset.y == "NORMAL")
    result: dict[str, dict[str, float]] = {}
    for signal in SIGNALS:
        means = dataset.X[normal, names[f"{signal}__mean"]]
        within_std = dataset.X[normal, names[f"{signal}__std"]]
        result[signal] = {
            "mean": float(np.mean(means)),
            "std": float(max(np.sqrt(np.var(means) + np.mean(within_std**2)), 1e-6)),
        }
    return result


def train(
    dataset: DatasetArrays, dataset_manifest: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    train_mask = dataset.splits == "train"
    validation_mask = dataset.splits == "validation"
    normal_train = train_mask & (dataset.y == "NORMAL")
    fault_train = train_mask & (dataset.y != "NORMAL")
    fault_validation = validation_mask & (dataset.y != "NORMAL")

    anomaly_indices = np.asarray(
        [
            index
            for index, name in enumerate(dataset.feature_names)
            if name.endswith(ANOMALY_SUFFIXES)
        ],
        dtype=int,
    )
    center, scale = robust_parameters(dataset.X[normal_train][:, anomaly_indices])
    robust_validation_scores = robust_scores(
        dataset.X[validation_mask][:, anomaly_indices], center, scale
    )
    robust_threshold = choose_anomaly_threshold(
        dataset.y[validation_mask], robust_validation_scores
    )
    robust_validation = anomaly_metrics(
        dataset.y[validation_mask], robust_validation_scores, robust_threshold
    )

    isolation = IsolationForest(
        n_estimators=160,
        max_samples="auto",
        contamination="auto",
        random_state=RANDOM_SEED,
        n_jobs=-1,
    )
    isolation.fit(dataset.X[normal_train])
    isolation_validation_scores = -isolation.decision_function(dataset.X[validation_mask])
    isolation_threshold = choose_anomaly_threshold(
        dataset.y[validation_mask], isolation_validation_scores
    )
    isolation_validation = anomaly_metrics(
        dataset.y[validation_mask], isolation_validation_scores, isolation_threshold
    )
    anomaly_candidates = {
        "robust_statistical": (robust_validation, robust_threshold, None, robust_validation_scores),
        "isolation_forest": (
            isolation_validation,
            isolation_threshold,
            isolation,
            isolation_validation_scores,
        ),
    }
    anomaly_name = max(anomaly_candidates, key=lambda name: anomaly_candidates[name][0]["pr_auc"])
    selected_anomaly = anomaly_candidates[anomaly_name]

    classifiers: dict[str, Any] = {
        "logistic_regression": Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        max_iter=2000, class_weight="balanced", random_state=RANDOM_SEED
                    ),
                ),
            ]
        ),
        "decision_tree": DecisionTreeClassifier(
            max_depth=10, min_samples_leaf=3, class_weight="balanced", random_state=RANDOM_SEED
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=160,
            max_depth=12,
            min_samples_leaf=2,
            class_weight="balanced_subsample",
            random_state=RANDOM_SEED,
            n_jobs=-1,
        ),
    }
    classifier_validation: dict[str, dict[str, Any]] = {}
    for name, estimator in classifiers.items():
        estimator.fit(dataset.X[fault_train], dataset.y[fault_train])
        predicted = estimator.predict(dataset.X[fault_validation])
        classifier_validation[name] = classification_metrics(
            dataset.y[fault_validation], predicted, FAULT_CLASSES
        )
    rules_predicted = deterministic_rule_predict(dataset.X[fault_validation], dataset.feature_names)
    classifier_validation["deterministic_rules"] = classification_metrics(
        dataset.y[fault_validation], rules_predicted, FAULT_CLASSES
    )

    learned_names = list(classifiers)
    classifier_name = max(learned_names, key=lambda name: classifier_validation[name]["macro_f1"])
    selected_base = classifiers[classifier_name]
    splitter = StratifiedGroupKFold(n_splits=3, shuffle=True, random_state=RANDOM_SEED)
    folds = list(
        splitter.split(
            dataset.X[fault_train],
            dataset.y[fault_train],
            groups=dataset.scenario_ids[fault_train],
        )
    )
    calibrated = CalibratedClassifierCV(selected_base, method="sigmoid", cv=folds, n_jobs=-1)
    calibrated.fit(dataset.X[fault_train], dataset.y[fault_train])
    validation_probabilities = calibrated.predict_proba(dataset.X[fault_validation])
    confidence_threshold = choose_confidence_threshold(
        dataset.y[fault_validation], validation_probabilities, calibrated.classes_
    )

    selected_scores = selected_anomaly[3]
    anomaly_scale = float(max(np.std(selected_scores), 1e-6))
    bundle: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "dataset_version": DATASET_VERSION,
        "window_size": 20,
        "inference_stride": 5,
        "feature_names": dataset.feature_names,
        "anomaly_kind": anomaly_name,
        "anomaly_model": selected_anomaly[2],
        "anomaly_threshold": float(selected_anomaly[1]),
        "anomaly_score_scale": anomaly_scale,
        "robust_center": center,
        "robust_scale": scale,
        "anomaly_feature_indices": anomaly_indices,
        "anomaly_top_k": 1,
        "classifier_name": classifier_name,
        "classifier": calibrated,
        "confidence_threshold": confidence_threshold,
        "normal_signal_stats": _normal_signal_stats(dataset, train_mask),
    }
    validation_summary = {
        "anomaly_candidates": {name: values[0] for name, values in anomaly_candidates.items()},
        "selected_anomaly": anomaly_name,
        "classifier_candidates": classifier_validation,
        "selected_classifier": classifier_name,
        "calibration": {
            "method": "CalibratedClassifierCV sigmoid, scenario-group 3-fold",
            "brier": multiclass_brier(
                dataset.y[fault_validation], validation_probabilities, calibrated.classes_
            ),
            "ece": expected_calibration_error(
                dataset.y[fault_validation], validation_probabilities, calibrated.classes_
            ),
            "confidence_threshold": confidence_threshold,
        },
        "dataset_manifest_sha256": dataset_manifest["manifest_sha256"],
    }
    return bundle, validation_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and freeze Phase 3 diagnosis models")
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
    parser.add_argument("--validation-report", type=Path, default=Path("output/validation.json"))
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    dataset_manifest = json.loads(args.dataset_manifest.read_text(encoding="utf-8"))
    if dataset_manifest["dataset_content_sha256"] != content_hash(dataset):
        raise RuntimeError("dataset content hash does not match manifest")
    bundle, validation = train(dataset, dataset_manifest)
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, args.artifact, compress=3)
    artifact_sha = hashlib.sha256(args.artifact.read_bytes()).hexdigest()
    root = Path(__file__).resolve().parents[2]
    model_manifest = {
        "model_version": MODEL_VERSION,
        "model_type": {
            "anomaly": bundle["anomaly_kind"],
            "classifier": bundle["classifier_name"],
            "calibration": "sigmoid",
        },
        "hyperparameters": {
            "window_size": bundle["window_size"],
            "inference_stride": bundle["inference_stride"],
            "random_seed": RANDOM_SEED,
        },
        "training_dataset_version": DATASET_VERSION,
        "dataset_manifest_sha256": dataset_manifest["manifest_sha256"],
        "feature_version": FEATURE_VERSION,
        "telemetry_schema_major": 1,
        "library_versions": {
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "thresholds": {
            "anomaly": bundle["anomaly_threshold"],
            "uncertain_confidence": bundle["confidence_threshold"],
        },
        "validation_metrics": validation,
        "artifact_sha256": artifact_sha,
        "created_at": datetime.now(UTC).isoformat(),
        "code_git_sha": _git_sha(root),
    }
    args.model_manifest.write_text(
        json.dumps(model_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.validation_report.parent.mkdir(parents=True, exist_ok=True)
    args.validation_report.write_text(
        json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(model_manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
