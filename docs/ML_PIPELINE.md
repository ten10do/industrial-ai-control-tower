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

The frozen test is read once by the final `industrial_ml.evaluation` command after model selection.
It checks the stored test hash before reporting anomaly, classification, calibration, confusion,
detection-delay, and error-analysis results.

## Reproduction commands

From `ml/` with Python 3.11:

```bash
pip install -r requirements-dev.txt
python -m industrial_ml.dataset
python -m industrial_ml.training
python -m industrial_ml.evaluation
```

The first command creates the ignored dataset plus its manifest. Training consumes only train and
validation splits and writes the selected artifact and model manifest to `backend/artifacts/`.
Evaluation verifies the frozen hash and writes the formal reports under `docs/evaluation/`.

CI deliberately runs only deterministic unit tests and tiny training/serialization smoke tests:

```bash
pytest
ruff check .
ruff format --check .
mypy industrial_ml tests
```

## Serving behavior

At startup the backend verifies artifact SHA-256, `diagnosis-v1`, `features-v1`, telemetry schema
major version, and exact NumPy/scikit-learn/joblib versions. Missing, corrupt, or incompatible
artifacts make the diagnosis capability unavailable and `/ready` returns 503 when that capability
is enabled. Telemetry ingestion can continue; no random or rule-based result is substituted.

Each device uses a bounded deque. PostgreSQL restores the last 20 samples after restart. Inference
runs every five accepted, newest samples and executes outside the event loop. Results and audit
events are persisted, with counters for inference, failures, uncertainty, latency, and prediction
distribution. An inference exception is persisted as `FAILED`, never NORMAL.
