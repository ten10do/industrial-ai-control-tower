"""Deterministic simulator scenario generation and scenario-group dataset splitting."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from app.ml.features import (
    FEATURE_VERSION,
    FeatureExtractor,
    FeatureValidationError,
    TelemetryWindow,
    WindowSample,
)
from simulator.faults import FaultConfig, FaultManager
from simulator.models import IndustrialMotor

DATASET_VERSION = "motor-sim-v1"
CLASSES = (
    "NORMAL",
    "BEARING_WEAR",
    "OVERLOAD",
    "OVERHEATING",
    "MISALIGNMENT",
    "SENSOR_FAILURE",
)
DEFAULT_COUNTS = {
    "NORMAL": 40,
    "BEARING_WEAR": 32,
    "OVERLOAD": 32,
    "OVERHEATING": 32,
    "MISALIGNMENT": 32,
    "SENSOR_FAILURE": 32,
}


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    scenario_id: str
    seed: int
    fault_type: str
    severity: float
    start_tick: int
    duration: int
    initial_load_pct: float
    ticks: int
    split: str


@dataclass(slots=True)
class DatasetArrays:
    X: np.ndarray
    y: np.ndarray
    scenario_ids: np.ndarray
    seeds: np.ndarray
    splits: np.ndarray
    window_end_ticks: np.ndarray
    fault_start_ticks: np.ndarray
    scenario_severity: np.ndarray
    feature_names: tuple[str, ...]
    rejected_windows: int
    rejection_reasons: dict[str, int]


def _git_sha(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def build_scenarios(
    counts: dict[str, int] | None = None, *, generation_seed: int = 20260917, ticks: int = 180
) -> list[ScenarioSpec]:
    """Build class-stratified scenarios with globally unique seeds and group splits."""
    counts = counts or DEFAULT_COUNTS
    rng = random.Random(generation_seed)
    scenarios: list[ScenarioSpec] = []
    seed_cursor = generation_seed * 10
    for fault_type in CLASSES:
        count = counts[fault_type]
        indices = list(range(count))
        rng.shuffle(indices)
        train_end = round(count * 0.60)
        validation_end = train_end + round(count * 0.20)
        split_by_index = {
            index: (
                "train"
                if position < train_end
                else "validation"
                if position < validation_end
                else "test"
            )
            for position, index in enumerate(indices)
        }
        for index in range(count):
            scenario_rng = random.Random(seed_cursor)
            start_tick = scenario_rng.randint(35, 55) if fault_type != "NORMAL" else -1
            duration = scenario_rng.randint(55, 75) if fault_type != "NORMAL" else 0
            severity = scenario_rng.uniform(0.55, 1.0) if fault_type != "NORMAL" else 0.0
            scenarios.append(
                ScenarioSpec(
                    scenario_id=f"{fault_type.lower()}-{index:03d}",
                    seed=seed_cursor,
                    fault_type=fault_type,
                    severity=round(severity, 4),
                    start_tick=start_tick,
                    duration=duration,
                    initial_load_pct=round(scenario_rng.uniform(35.0, 75.0), 3),
                    ticks=ticks,
                    split=split_by_index[index],
                )
            )
            seed_cursor += 1
    return scenarios


def generate_scenario(
    spec: ScenarioSpec, extractor: FeatureExtractor
) -> tuple[list[tuple[np.ndarray, str, int]], Counter[str]]:
    """Generate one independent scenario; labels never enter the extractor input."""
    motor = IndustrialMotor(
        device_id=spec.scenario_id,
        seed=spec.seed,
        initial_load_pct=spec.initial_load_pct,
    )
    manager: FaultManager | None = None
    if spec.fault_type != "NORMAL":
        manager = FaultManager(motor.rng)
        manager.add_fault(
            FaultConfig(
                fault_type=spec.fault_type,
                start_tick=spec.start_tick,
                duration=spec.duration,
                severity=spec.severity,
                ramp_up_ticks=10,
                recovery_ticks=15,
                target_signal="STUCK" if spec.fault_type == "SENSOR_FAILURE" else None,
            )
        )

    start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=spec.seed % 365)
    samples: list[WindowSample] = []
    labels: list[str] = []
    frozen_sensor_value: float | None = None
    for tick in range(spec.ticks):
        effects: dict[str, float | int] = {}
        label = "NORMAL"
        if manager is not None:
            effects = manager.effects_for_tick(tick)
            active = manager.active_fault_types(tick)
            label = active[0] if active else "NORMAL"
            motor.set_fault_state(manager.current_state_label())
        telemetry = motor.step(effects, timestamp=start + timedelta(seconds=tick))
        if spec.fault_type == "SENSOR_FAILURE":
            if tick == spec.start_tick - 1:
                frozen_sensor_value = telemetry.temperature_c
            if label == "SENSOR_FAILURE" and frozen_sensor_value is not None:
                sensor_value = frozen_sensor_value
                if tick % 7 == 0:
                    sensor_value += 20.0 * spec.severity
                telemetry = telemetry.model_copy(update={"temperature_c": round(sensor_value, 2)})
        # WindowSample has no label/fault_state field. Extra simulator fields are discarded here.
        samples.append(WindowSample.model_validate(telemetry, from_attributes=True))
        labels.append(label)

    rows: list[tuple[np.ndarray, str, int]] = []
    rejections: Counter[str] = Counter()
    for end_index in range(extractor.window_size - 1, len(samples), 5):
        window_samples = samples[end_index - extractor.window_size + 1 : end_index + 1]
        window = TelemetryWindow(device_id=spec.scenario_id, samples=window_samples)
        try:
            vector = extractor.extract(window)
        except FeatureValidationError as exc:
            rejections[str(exc)] += 1
            continue
        rows.append((vector, labels[end_index], end_index))
    return rows, rejections


def generate_dataset(scenarios: list[ScenarioSpec], window_size: int = 20) -> DatasetArrays:
    extractor = FeatureExtractor(window_size=window_size)
    extractor.validate_schema()
    features: list[np.ndarray] = []
    labels: list[str] = []
    scenario_ids: list[str] = []
    seeds: list[int] = []
    splits: list[str] = []
    window_ticks: list[int] = []
    fault_starts: list[int] = []
    severities: list[float] = []
    rejections: Counter[str] = Counter()
    for spec in scenarios:
        scenario_rows, scenario_rejections = generate_scenario(spec, extractor)
        rejections.update(scenario_rejections)
        for vector, label, end_tick in scenario_rows:
            features.append(vector)
            labels.append(label)
            scenario_ids.append(spec.scenario_id)
            seeds.append(spec.seed)
            splits.append(spec.split)
            window_ticks.append(end_tick)
            fault_starts.append(spec.start_tick)
            severities.append(spec.severity)
    return DatasetArrays(
        X=np.vstack(features),
        y=np.asarray(labels),
        scenario_ids=np.asarray(scenario_ids),
        seeds=np.asarray(seeds, dtype=np.int64),
        splits=np.asarray(splits),
        window_end_ticks=np.asarray(window_ticks, dtype=np.int64),
        fault_start_ticks=np.asarray(fault_starts, dtype=np.int64),
        scenario_severity=np.asarray(severities, dtype=float),
        feature_names=extractor.feature_names,
        rejected_windows=sum(rejections.values()),
        rejection_reasons=dict(rejections),
    )


def content_hash(dataset: DatasetArrays) -> str:
    digest = hashlib.sha256()
    for array in (
        dataset.X,
        dataset.y,
        dataset.scenario_ids,
        dataset.seeds,
        dataset.splits,
        dataset.window_end_ticks,
        dataset.fault_start_ticks,
        dataset.scenario_severity,
    ):
        digest.update(np.ascontiguousarray(array).tobytes())
    digest.update("\n".join(dataset.feature_names).encode())
    digest.update(str(dataset.rejected_windows).encode())
    digest.update(json.dumps(dataset.rejection_reasons, sort_keys=True).encode())
    return digest.hexdigest()


def save_dataset(dataset: DatasetArrays, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        X=dataset.X,
        y=dataset.y,
        scenario_ids=dataset.scenario_ids,
        seeds=dataset.seeds,
        splits=dataset.splits,
        window_end_ticks=dataset.window_end_ticks,
        fault_start_ticks=dataset.fault_start_ticks,
        scenario_severity=dataset.scenario_severity,
        feature_names=np.asarray(dataset.feature_names),
        rejected_windows=np.asarray(dataset.rejected_windows),
        rejection_reasons=np.asarray(json.dumps(dataset.rejection_reasons, sort_keys=True)),
    )


def load_dataset(path: Path) -> DatasetArrays:
    with np.load(path, allow_pickle=False) as data:
        return DatasetArrays(
            X=data["X"],
            y=data["y"],
            scenario_ids=data["scenario_ids"],
            seeds=data["seeds"],
            splits=data["splits"],
            window_end_ticks=data["window_end_ticks"],
            fault_start_ticks=data["fault_start_ticks"],
            scenario_severity=data["scenario_severity"],
            feature_names=tuple(data["feature_names"].tolist()),
            rejected_windows=int(data["rejected_windows"]),
            rejection_reasons=json.loads(str(data["rejection_reasons"])),
        )


def build_manifest(
    dataset: DatasetArrays, scenarios: list[ScenarioSpec], root: Path
) -> dict[str, Any]:
    split_scenarios = {
        split: sorted(spec.scenario_id for spec in scenarios if spec.split == split)
        for split in ("train", "validation", "test")
    }
    test_mask = dataset.splits == "test"
    frozen_test_digest = hashlib.sha256()
    frozen_test_digest.update(np.ascontiguousarray(dataset.X[test_mask]).tobytes())
    frozen_test_digest.update(np.ascontiguousarray(dataset.y[test_mask]).tobytes())
    manifest: dict[str, Any] = {
        "dataset_version": DATASET_VERSION,
        "feature_version": FEATURE_VERSION,
        "simulator_git_sha": _git_sha(root),
        "generation": {
            "seed": 20260917,
            "window_size": 20,
            "stride": 5,
            "scenario_count": len(scenarios),
            "ticks_per_scenario": sorted({spec.ticks for spec in scenarios}),
        },
        "scenario_count": len(scenarios),
        "window_count": len(dataset.y),
        "rejected_window_count": dataset.rejected_windows,
        "rejection_reasons": dataset.rejection_reasons,
        "scenario_class_distribution": dict(Counter(spec.fault_type for spec in scenarios)),
        "window_class_distribution": dict(Counter(dataset.y.tolist())),
        "split_scenario_counts": {key: len(value) for key, value in split_scenarios.items()},
        "split_scenarios": split_scenarios,
        "seeds": {spec.scenario_id: spec.seed for spec in scenarios},
        "scenarios": [asdict(spec) for spec in scenarios],
        "dataset_content_sha256": content_hash(dataset),
        "frozen_test_sha256": frozen_test_digest.hexdigest(),
        "created_at": datetime.now(UTC).isoformat(),
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    return manifest


def write_manifest(manifest: dict[str, Any], path: Path) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("frozen_test_sha256") != manifest["frozen_test_sha256"]:
            raise RuntimeError("refusing to overwrite a different frozen test set")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic Phase 3 simulator dataset")
    parser.add_argument("--output", type=Path, default=Path("data/phase3_dataset.npz"))
    parser.add_argument("--manifest", type=Path, default=Path("manifests/dataset_manifest.json"))
    parser.add_argument("--small", action="store_true", help="Generate a CI-sized fixture")
    args = parser.parse_args()
    counts = dict.fromkeys(CLASSES, 2) if args.small else DEFAULT_COUNTS
    ticks = 80 if args.small else 180
    scenarios = build_scenarios(counts, ticks=ticks)
    dataset = generate_dataset(scenarios)
    root = Path(__file__).resolve().parents[2]
    save_dataset(dataset, args.output)
    manifest = build_manifest(dataset, scenarios, root)
    write_manifest(manifest, args.manifest)
    print(json.dumps({"dataset": str(args.output), **manifest}, indent=2))


if __name__ == "__main__":
    main()
