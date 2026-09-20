"""Integrity-checked runtime for the frozen Phase 3 diagnosis artifact."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Literal, cast

import joblib
import numpy as np
import sklearn
from numpy.typing import NDArray
from pydantic import BaseModel, Field

from app.ml.features import FEATURE_VERSION, SIGNALS, FeatureExtractor, TelemetryWindow, sigmoid

MODEL_VERSION = "diagnosis-v1.1"
logger = logging.getLogger(__name__)


class ModelCompatibilityError(RuntimeError):
    """Artifact integrity or schema compatibility check failed."""


class DiagnosticEvidence(BaseModel):
    signal: str
    observation: float
    normal_baseline: float
    deviation: float
    trend: Literal["increasing", "decreasing", "stable"]


class DiagnosisPrediction(BaseModel):
    device_id: str
    window_start: str
    window_end: str
    status: Literal["NORMAL", "FAULT", "UNCERTAIN", "FAILED"]
    fault_type: str | None
    anomaly_score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    severity: Literal["NORMAL", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    evidence: list[DiagnosticEvidence]
    model_version: str
    feature_version: str


class ModelRuntime:
    """Load once, then run deterministic window inference without training."""

    def __init__(self, bundle: dict[str, Any], manifest: dict[str, Any]) -> None:
        self.bundle = bundle
        self.manifest = manifest
        self.extractor = FeatureExtractor(window_size=int(bundle["window_size"]))
        self.extractor.validate_schema()
        if tuple(bundle["feature_names"]) != self.extractor.feature_names:
            raise ModelCompatibilityError("artifact feature names do not match runtime schema")

    @classmethod
    def load(cls, artifact_path: Path, manifest_path: Path) -> ModelRuntime:
        if not artifact_path.is_file() or not manifest_path.is_file():
            raise ModelCompatibilityError("model artifact or manifest does not exist")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if digest != manifest.get("artifact_sha256"):
            raise ModelCompatibilityError("model artifact SHA256 mismatch")
        if manifest.get("model_version") != MODEL_VERSION:
            raise ModelCompatibilityError("unsupported model version")
        if manifest.get("feature_version") != FEATURE_VERSION:
            raise ModelCompatibilityError("unsupported feature version")
        if manifest.get("telemetry_schema_major") != 1:
            raise ModelCompatibilityError("unsupported telemetry schema version")
        actual_libraries = {
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        }
        if manifest.get("library_versions") != actual_libraries:
            raise ModelCompatibilityError("model/runtime library versions do not match")
        bundle = cast(dict[str, Any], joblib.load(artifact_path))
        if bundle.get("model_version") != manifest["model_version"]:
            raise ModelCompatibilityError("artifact/manifest model version mismatch")
        runtime = cls(bundle, manifest)
        logger.info(
            "diagnosis_model_loaded",
            extra={"model_version": MODEL_VERSION, "feature_version": FEATURE_VERSION},
        )
        return runtime

    def anomaly_raw(self, features: NDArray[np.float64]) -> float:
        if self.bundle["anomaly_kind"] == "isolation_forest":
            decision = self.bundle["anomaly_model"].decision_function(features.reshape(1, -1))[0]
            return float(-decision)
        indices = self.bundle.get("anomaly_feature_indices", np.arange(len(features)))
        selected = features[indices]
        z = np.abs((selected - self.bundle["robust_center"]) / self.bundle["robust_scale"])
        top_k = int(self.bundle.get("anomaly_top_k", 5))
        return float(np.mean(np.partition(z, -top_k)[-top_k:]))

    def predict(self, window: TelemetryWindow) -> DiagnosisPrediction:
        features = self.extractor.extract(window)
        raw_score = self.anomaly_raw(features)
        threshold = float(self.bundle["anomaly_threshold"])
        scale = max(float(self.bundle["anomaly_score_scale"]), 1e-6)
        anomaly_probability = sigmoid((raw_score - threshold) / scale)
        is_anomaly = raw_score >= threshold
        evidence = self._evidence(window)

        if not is_anomaly:
            return DiagnosisPrediction(
                device_id=window.device_id,
                window_start=window.start.isoformat(),
                window_end=window.end.isoformat(),
                status="NORMAL",
                fault_type="NORMAL",
                anomaly_score=anomaly_probability,
                confidence=max(0.0, 1.0 - anomaly_probability),
                severity="NORMAL",
                evidence=evidence,
                model_version=MODEL_VERSION,
                feature_version=FEATURE_VERSION,
            )

        probabilities = self.bundle["classifier"].predict_proba(features.reshape(1, -1))[0]
        classes = self.bundle["classifier"].classes_
        index = int(np.argmax(probabilities))
        confidence = float(probabilities[index])
        fault_type = str(classes[index])
        uncertain = confidence < float(self.bundle["confidence_threshold"])
        return DiagnosisPrediction(
            device_id=window.device_id,
            window_start=window.start.isoformat(),
            window_end=window.end.isoformat(),
            status="UNCERTAIN" if uncertain else "FAULT",
            fault_type=None if uncertain else fault_type,
            anomaly_score=anomaly_probability,
            confidence=confidence,
            severity=self._severity(anomaly_probability, evidence),
            evidence=evidence,
            model_version=MODEL_VERSION,
            feature_version=FEATURE_VERSION,
        )

    def _evidence(self, window: TelemetryWindow) -> list[DiagnosticEvidence]:
        signal_stats: dict[str, dict[str, float]] = self.bundle["normal_signal_stats"]
        candidates: list[tuple[float, DiagnosticEvidence]] = []
        for signal in SIGNALS:
            values = np.asarray([getattr(sample, signal) for sample in window.samples], dtype=float)
            observation = float(values[-1])
            baseline = float(signal_stats[signal]["mean"])
            std = max(float(signal_stats[signal]["std"]), 1e-6)
            deviation = observation - baseline
            slope = float(values[-1] - values[0]) / max(len(values) - 1, 1)
            trend: Literal["increasing", "decreasing", "stable"]
            if slope > std * 0.03:
                trend = "increasing"
            elif slope < -std * 0.03:
                trend = "decreasing"
            else:
                trend = "stable"
            candidates.append(
                (
                    abs(deviation) / std,
                    DiagnosticEvidence(
                        signal=signal,
                        observation=round(observation, 4),
                        normal_baseline=round(baseline, 4),
                        deviation=round(deviation, 4),
                        trend=trend,
                    ),
                )
            )
        return [item[1] for item in sorted(candidates, key=lambda item: item[0], reverse=True)[:3]]

    @staticmethod
    def _severity(
        anomaly_probability: float, evidence: list[DiagnosticEvidence]
    ) -> Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
        max_deviation = max((abs(item.deviation) for item in evidence), default=0.0)
        if anomaly_probability >= 0.95 or max_deviation >= 30:
            return "CRITICAL"
        if anomaly_probability >= 0.8 or max_deviation >= 15:
            return "HIGH"
        if anomaly_probability >= 0.65 or max_deviation >= 7:
            return "MEDIUM"
        return "LOW"
