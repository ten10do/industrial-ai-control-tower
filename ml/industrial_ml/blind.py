"""Create and freeze the never-before-seen Phase 3.1 blind acceptance set."""

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
from app.ml.features import FeatureExtractor, FeatureValidationError, TelemetryWindow, WindowSample
from simulator.faults import FaultConfig, FaultManager
from simulator.models import IndustrialMotor

from industrial_ml.dataset import (
    CLASSES,
    DATASET_VERSION,
    DatasetArrays,
    content_hash,
    save_dataset,
)

BLIND_DATASET_VERSION = "motor-sim-blind-v1"
BLIND_GENERATION_SEED = 20260920
BLIND_SEED_BASE = 2_026_092_000
BLIND_COUNT_PER_CLASS = 20


@dataclass(frozen=True, slots=True)
class BlindScenarioSpec:
    scenario_id: str
    seed: int
    fault_type: str
    severity: float
    start_tick: int
    duration: int
    initial_load_pct: float
    ticks: int
    ramp_up_ticks: int
    recovery_ticks: int
    sensor_spike_interval: int
    sensor_spike_amplitude: float
    split: str = "blind"


def _git_sha(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def build_blind_scenarios(
    existing_seeds: set[int],
    *,
    count_per_class: int = BLIND_COUNT_PER_CLASS,
    ticks: int = 200,
) -> list[BlindScenarioSpec]:
    """Allocate deterministic new seeds before any model-based metric is computed."""
    scenarios: list[BlindScenarioSpec] = []
    seed_cursor = BLIND_SEED_BASE
    for fault_type in CLASSES:
        for index in range(count_per_class):
            seed = seed_cursor
            seed_cursor += 1
            if seed in existing_seeds:
                raise RuntimeError(f"blind seed overlaps an existing scenario: {seed}")
            rng = random.Random(seed)
            is_normal = fault_type == "NORMAL"
            scenarios.append(
                BlindScenarioSpec(
                    scenario_id=f"blind-{fault_type.lower()}-{index:03d}",
                    seed=seed,
                    fault_type=fault_type,
                    severity=0.0 if is_normal else round(rng.uniform(0.45, 1.0), 4),
                    start_tick=-1 if is_normal else rng.randint(30, 65),
                    duration=0 if is_normal else rng.randint(45, 85),
                    initial_load_pct=round(rng.uniform(25.0, 90.0), 3),
                    ticks=ticks,
                    ramp_up_ticks=0 if is_normal else rng.randint(6, 18),
                    recovery_ticks=0 if is_normal else rng.randint(15, 30),
                    sensor_spike_interval=5 + seed % 5,
                    sensor_spike_amplitude=round(rng.uniform(15.0, 26.0), 3),
                )
            )
    return scenarios


def generate_blind_scenario(
    spec: BlindScenarioSpec, extractor: FeatureExtractor
) -> tuple[list[tuple[np.ndarray, str, int]], Counter[str]]:
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
                ramp_up_ticks=spec.ramp_up_ticks,
                recovery_ticks=spec.recovery_ticks,
                target_signal="STUCK" if spec.fault_type == "SENSOR_FAILURE" else None,
            )
        )

    start = datetime(2026, 7, 1, tzinfo=UTC) + timedelta(days=spec.seed % 120)
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
                if tick % spec.sensor_spike_interval == 0:
                    sensor_value += spec.sensor_spike_amplitude * spec.severity
                telemetry = telemetry.model_copy(update={"temperature_c": round(sensor_value, 2)})
        samples.append(WindowSample.model_validate(telemetry, from_attributes=True))
        labels.append(label)

    rows: list[tuple[np.ndarray, str, int]] = []
    rejections: Counter[str] = Counter()
    for end_tick in range(extractor.window_size - 1, len(samples), 5):
        window = TelemetryWindow(
            device_id=spec.scenario_id,
            samples=samples[end_tick - extractor.window_size + 1 : end_tick + 1],
        )
        try:
            vector = extractor.extract(window)
        except FeatureValidationError as exc:
            rejections[str(exc)] += 1
            continue
        rows.append((vector, labels[end_tick], end_tick))
    return rows, rejections


def generate_blind_dataset(scenarios: list[BlindScenarioSpec]) -> DatasetArrays:
    extractor = FeatureExtractor(window_size=20)
    features: list[np.ndarray] = []
    labels: list[str] = []
    scenario_ids: list[str] = []
    seeds: list[int] = []
    end_ticks: list[int] = []
    starts: list[int] = []
    severities: list[float] = []
    rejections: Counter[str] = Counter()
    for spec in scenarios:
        rows, rejected = generate_blind_scenario(spec, extractor)
        rejections.update(rejected)
        for vector, label, end_tick in rows:
            features.append(vector)
            labels.append(label)
            scenario_ids.append(spec.scenario_id)
            seeds.append(spec.seed)
            end_ticks.append(end_tick)
            starts.append(spec.start_tick)
            severities.append(spec.severity)
    return DatasetArrays(
        X=np.vstack(features),
        y=np.asarray(labels),
        scenario_ids=np.asarray(scenario_ids),
        seeds=np.asarray(seeds, dtype=np.int64),
        splits=np.asarray(["blind"] * len(labels)),
        window_end_ticks=np.asarray(end_ticks, dtype=np.int64),
        fault_start_ticks=np.asarray(starts, dtype=np.int64),
        scenario_severity=np.asarray(severities, dtype=float),
        feature_names=extractor.feature_names,
        rejected_windows=sum(rejections.values()),
        rejection_reasons=dict(rejections),
    )


def build_blind_manifest(
    dataset: DatasetArrays,
    scenarios: list[BlindScenarioSpec],
    existing_seeds: set[int],
    root: Path,
) -> dict[str, Any]:
    blind_seeds = {spec.seed for spec in scenarios}
    if blind_seeds.intersection(existing_seeds):
        raise RuntimeError("blind seed overlap detected while building manifest")
    holdout_digest = hashlib.sha256()
    label_feature_digest = hashlib.sha256()
    label_feature_digest.update(np.ascontiguousarray(dataset.X).tobytes())
    label_feature_digest.update(np.ascontiguousarray(dataset.y).tobytes())
    for array in (
        dataset.X,
        dataset.y,
        dataset.scenario_ids,
        dataset.seeds,
        dataset.window_end_ticks,
        dataset.fault_start_ticks,
        dataset.scenario_severity,
    ):
        holdout_digest.update(np.ascontiguousarray(array).tobytes())
    manifest: dict[str, Any] = {
        "dataset_version": BLIND_DATASET_VERSION,
        "parent_training_dataset_version": DATASET_VERSION,
        "generation_config_version": "blind-config-v1",
        "generation_code_git_sha": _git_sha(root),
        "created_at": datetime.now(UTC).isoformat(),
        "scenario_count": len(scenarios),
        "normal_scenario_count": sum(spec.fault_type == "NORMAL" for spec in scenarios),
        "class_scenario_distribution": dict(Counter(spec.fault_type for spec in scenarios)),
        "window_count": len(dataset.y),
        "rejected_window_count": dataset.rejected_windows,
        "rejection_reasons": dataset.rejection_reasons,
        "generation": {
            "allocation_seed": BLIND_GENERATION_SEED,
            "seed_base": BLIND_SEED_BASE,
            "count_per_class": BLIND_COUNT_PER_CLASS,
            "ticks": 200,
            "window_size": 20,
            "stride": 5,
            "initial_load_pct_range": [25.0, 90.0],
            "fault_severity_range": [0.45, 1.0],
            "fault_start_tick_range": [30, 65],
            "fault_duration_range": [45, 85],
            "ramp_up_tick_range": [6, 18],
            "recovery_tick_range": [15, 30],
        },
        "new_seed_verification": {
            "existing_seed_count": len(existing_seeds),
            "blind_seed_count": len(blind_seeds),
            "overlap_count": 0,
        },
        "scenario_ids": [spec.scenario_id for spec in scenarios],
        "seeds": [spec.seed for spec in scenarios],
        "scenarios": [asdict(spec) for spec in scenarios],
        "dataset_content_sha256": content_hash(dataset),
        "frozen_label_feature_sha256": label_feature_digest.hexdigest(),
        "blind_holdout_sha256": holdout_digest.hexdigest(),
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest["manifest_sha256"] = hashlib.sha256(canonical).hexdigest()
    return manifest


def write_blind_manifest(manifest: dict[str, Any], path: Path) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("blind_holdout_sha256") != manifest["blind_holdout_sha256"]:
            raise RuntimeError("refusing to replace the frozen blind holdout")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--existing-manifest", type=Path, default=Path("manifests/dataset_manifest.json")
    )
    parser.add_argument("--output", type=Path, default=Path("data/phase3_blind_holdout_v1.npz"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("manifests/blind_holdout_manifest_v1.json")
    )
    args = parser.parse_args()
    existing_manifest = json.loads(args.existing_manifest.read_text(encoding="utf-8"))
    existing_seeds = set(existing_manifest["seeds"].values())
    scenarios = build_blind_scenarios(existing_seeds)
    dataset = generate_blind_dataset(scenarios)
    root = Path(__file__).resolve().parents[2]
    manifest = build_blind_manifest(dataset, scenarios, existing_seeds, root)
    save_dataset(dataset, args.output)
    write_blind_manifest(manifest, args.manifest)
    print(
        json.dumps(
            {
                "dataset_version": manifest["dataset_version"],
                "scenario_count": manifest["scenario_count"],
                "normal_scenario_count": manifest["normal_scenario_count"],
                "new_seed_verification": manifest["new_seed_verification"],
                "dataset_content_sha256": manifest["dataset_content_sha256"],
                "blind_holdout_sha256": manifest["blind_holdout_sha256"],
                "manifest_sha256": manifest["manifest_sha256"],
                "generation_code_git_sha": manifest["generation_code_git_sha"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
