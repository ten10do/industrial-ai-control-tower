"""Training smoke, serialization compatibility, and uncertainty tests."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pytest
import sklearn
from app.ml.features import (
    FEATURE_VERSION,
    SIGNALS,
    FeatureExtractor,
    TelemetryWindow,
    WindowSample,
)
from app.ml.runtime import MODEL_VERSION, ModelCompatibilityError, ModelRuntime

from industrial_ml.dataset import CLASSES, build_manifest, build_scenarios, generate_dataset
from industrial_ml.evaluation import evaluate
from industrial_ml.training import train


def normal_window() -> TelemetryWindow:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    samples = [
        WindowSample(
            timestamp=start + timedelta(seconds=index),
            temperature_c=50.0,
            bearing_temperature_c=53.0,
            vibration_mm_s=2.0,
            current_a=5.0,
            voltage_v=380.0,
            rpm=1440,
            load_pct=50.0,
            power_kw=3.0,
        )
        for index in range(20)
    ]
    return TelemetryWindow(device_id="MOTOR-001", samples=samples)


@pytest.fixture(scope="module")
def trained_bundle() -> tuple[dict[str, Any], dict[str, Any]]:
    scenarios = build_scenarios(dict.fromkeys(CLASSES, 5), ticks=100)
    dataset = generate_dataset(scenarios)
    root = Path(__file__).resolve().parents[2]
    manifest = build_manifest(dataset, scenarios, root)
    bundle, _ = train(dataset, manifest)
    return bundle, manifest


def test_tiny_training_save_load_and_predict(
    trained_bundle: tuple[dict[str, Any], dict[str, Any]], tmp_path: Path
) -> None:
    bundle, _ = trained_bundle
    artifact = tmp_path / "model.joblib"
    manifest_path = tmp_path / "manifest.json"
    joblib.dump(bundle, artifact)
    manifest = {
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "telemetry_schema_major": 1,
        "library_versions": {
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    runtime = ModelRuntime.load(artifact, manifest_path)
    prediction = runtime.predict(normal_window())
    assert prediction.status in {"NORMAL", "FAULT", "UNCERTAIN"}
    assert prediction.model_version == MODEL_VERSION


def test_corrupt_or_incompatible_artifact_is_rejected(
    trained_bundle: tuple[dict[str, Any], dict[str, Any]], tmp_path: Path
) -> None:
    bundle, _ = trained_bundle
    artifact = tmp_path / "model.joblib"
    joblib.dump(bundle, artifact)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "artifact_sha256": "wrong",
                "model_version": MODEL_VERSION,
                "feature_version": FEATURE_VERSION,
                "telemetry_schema_major": 1,
                "library_versions": {
                    "numpy": np.__version__,
                    "scikit_learn": sklearn.__version__,
                    "joblib": joblib.__version__,
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ModelCompatibilityError, match="SHA256"):
        ModelRuntime.load(artifact, manifest)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model_version", "diagnosis-v0", "model version"),
        ("feature_version", "features-v0", "feature version"),
        ("telemetry_schema_major", 2, "telemetry schema"),
    ],
)
def test_incompatible_versions_are_rejected(
    trained_bundle: tuple[dict[str, Any], dict[str, Any]],
    tmp_path: Path,
    field: str,
    value: str | int,
    message: str,
) -> None:
    bundle, _ = trained_bundle
    artifact = tmp_path / f"{field}.joblib"
    joblib.dump(bundle, artifact)
    manifest_data: dict[str, Any] = {
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "telemetry_schema_major": 1,
        "library_versions": {
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
    }
    manifest_data[field] = value
    manifest = tmp_path / f"{field}.json"
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")
    with pytest.raises(ModelCompatibilityError, match=message):
        ModelRuntime.load(artifact, manifest)


class LowConfidenceClassifier:
    classes_ = np.asarray(["BEARING_WEAR", "MISALIGNMENT", "OVERHEATING"])

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        return np.tile(np.asarray([0.34, 0.33, 0.33]), (len(features), 1))


def test_low_confidence_prediction_is_uncertain() -> None:
    extractor = FeatureExtractor()
    signal_stats = {name: {"mean": 1.0, "std": 1.0} for name in SIGNALS}
    bundle: dict[str, Any] = {
        "window_size": 20,
        "feature_names": extractor.feature_names,
        "anomaly_kind": "robust_statistical",
        "robust_center": np.zeros(76),
        "robust_scale": np.ones(76),
        "anomaly_threshold": -1.0,
        "anomaly_score_scale": 1.0,
        "classifier": LowConfidenceClassifier(),
        "confidence_threshold": 0.65,
        "normal_signal_stats": signal_stats,
    }
    prediction = ModelRuntime(bundle, {}).predict(normal_window())
    assert prediction.status == "UNCERTAIN"
    assert prediction.fault_type is None


def test_tiny_frozen_evaluation_smoke(
    trained_bundle: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    bundle, manifest = trained_bundle
    scenarios = build_scenarios(dict.fromkeys(CLASSES, 5), ticks=100)
    dataset = generate_dataset(scenarios)
    results = evaluate(dataset, bundle, manifest)
    assert results["test_scenarios"] == 6
    assert set(results["per_class_recall"]) == set(CLASSES) - {"NORMAL"}
    assert "fault_confusion_pairs" in results["error_analysis"]
