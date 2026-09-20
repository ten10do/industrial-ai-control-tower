# Phase 3 ML Diagnosis Pipeline

## Scope and claim

Phase 3 is a synthetic IndustrialMotor diagnosis benchmark and a deployable ML-engineering
pipeline. It proves deterministic data generation, leakage-safe evaluation, artifact integrity,
and online inference. It does **not** prove equivalent accuracy on real industrial motors. No LLM,
RAG, agent, planner, or work-order automation participates in diagnosis.

## Data and split

`industrial_ml.dataset` calls the Phase 1 `IndustrialMotor` and `FaultManager` directly. The formal
configuration generates 200 independent scenarios: 40 NORMAL and 32 each for BEARING_WEAR,
OVERLOAD, OVERHEATING, MISALIGNMENT, and SENSOR_FAILURE. Each scenario owns a unique seed, noise,
load profile, fault timing, duration, and severity.

Splitting is class-stratified by complete scenario/seed groups (approximately 60/20/20). No tick or
window from a scenario can cross splits. The manifest records every scenario, seed, split, class
distribution, generation settings, content hash, and frozen-test hash. After creation, writing a
different test hash is rejected.

Raw generated arrays live in ignored `ml/data/`. The reproducible manifest is tracked at
`ml/manifests/dataset_manifest.json`.

## Feature and label boundaries

The serving and training path share `backend/app/ml/features.py`. A 20-sample window at stride 5
produces 76 features: mean, standard deviation, min, max, median, slope, delta, range, and variance
for eight signals, plus four cross-signal features. `feature_version` is `features-v1`.

`WindowSample` accepts only timestamp and numeric sensor fields. `fault_state`, `fault_type`,
severity labels, scenario IDs, and scenario labels are forbidden by an explicit schema gate and
never enter the matrix. Missing timestamps, insufficient windows, NaN, infinity, and out-of-range
measurements are rejected and counted; values are never silently filled with zero.

## Models and selection

- Deterministic threshold rules establish the non-ML classification baseline.
- Logistic Regression and Decision Tree are simple learned baselines.
- Random Forest is the candidate classifier.
- A robust normal-statistics detector is compared with Isolation Forest trained only on normal
  training windows.
- Anomaly and uncertainty thresholds are selected from validation only.
- Class probabilities use sigmoid `CalibratedClassifierCV` with scenario-group three-fold splits.

The original frozen test was read once by `industrial_ml.evaluation`. It produced Normal FPR
5.1842% and is permanently retained as `EXPOSED_TEST_V1`; it is never reused to claim acceptance
after threshold changes. Its 38 false positives and the synthetic classifier separability audit
are preserved under `docs/evaluation/`.

`diagnosis-v1.1` uses a deterministic validation-only operating point: maximize anomaly recall,
tie-break by F1 and lower FPR, while requiring the two-sided Wilson 95% upper bound for validation
Normal FPR to be at most 5%. This selected threshold 46.708485 with validation FPR 3.1437%
(21/668), upper bound 4.7580%, and recall 51.5625%.

Before v1.1 was frozen, `industrial_ml.blind` allocated 120 new scenarios/seeds with wider load,
severity, timing, ramp, duration, and recovery ranges. The seed overlap with the original 200
scenarios is zero. The manifest and artifact were committed together before the one-shot
`industrial_ml.blind_evaluation` command revealed any label-based model metrics.

## Reproduction commands

From `ml/` with Python 3.11:

```bash
pip install -r requirements-dev.txt
python -m industrial_ml.dataset
python -m industrial_ml.exposed_analysis
python -m industrial_ml.separability_audit
python -m industrial_ml.blind
python -m industrial_ml.training
python -m industrial_ml.blind_evaluation
```

The first command creates the ignored dataset plus its manifest. Training consumes only train and
validation splits and writes the selected artifact and model manifest to `backend/artifacts/`.
The blind commands describe a release protocol, not an iterative tuning loop. Once blind metrics
are exposed, changing the artifact or holdout invalidates the acceptance claim. Generated arrays
remain ignored; manifests and reports are tracked.

CI deliberately runs only deterministic unit tests and tiny training/serialization smoke tests:

```bash
pytest
ruff check .
ruff format --check .
mypy industrial_ml tests
```

## Serving behavior

At startup the backend verifies artifact SHA-256, `diagnosis-v1.1`, `features-v1`, telemetry schema
major version, and exact NumPy/scikit-learn/joblib versions. Missing, corrupt, or incompatible
artifacts make the diagnosis capability unavailable and `/ready` returns 503 when that capability
is enabled. Telemetry ingestion can continue; no random or rule-based result is substituted.

Each device uses a bounded deque. PostgreSQL restores the last 20 samples after restart. Inference
runs every five accepted, newest samples and executes outside the event loop. Results and audit
events are persisted, with counters for inference, failures, uncertainty, latency, and prediction
distribution. An inference exception is persisted as `FAILED`, never NORMAL.
