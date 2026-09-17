# PHASE_3_FINAL_REPORT

## 1. STATUS

**PARTIAL**

The complete Phase 3 engineering chain is implemented and verified. Three of four frozen-test
acceptance targets passed. Normal false-positive rate was **5.1842%**, slightly above the required
5%; the frozen test was not used to retune the threshold. Phase 4 is therefore not ready.

## 2. Repository

- Path: `D:\industrial-ai-control-tower`
- Branch: `main`
- Evaluation code HEAD: `690356a1c04b933d2cd69a55a3a14ce2ba188d65`
- Git status: clean after the final report commit (the final handoff reports that commit SHA)

## 3. Dataset

- Scenarios: 200
- Accepted windows: 5,840
- Explicitly rejected invalid windows: 760 (670 motor-temperature range, 90 bearing-temperature range)
- Scenario classes: NORMAL 40; each of BEARING_WEAR, OVERLOAD, OVERHEATING, MISALIGNMENT,
  SENSOR_FAILURE 32
- Window classes: NORMAL 3,480; BEARING_WEAR 571; OVERLOAD 496; OVERHEATING 146;
  MISALIGNMENT 566; SENSOR_FAILURE 581
- Train: 119 scenarios / 3,474 windows
- Validation: 38 scenarios / 1,116 windows
- Test: 43 scenarios / 1,250 windows
- Dataset version: `motor-sim-v1`
- Dataset content SHA-256: `45dba0971a75661a462cb08cb7f90dbcb8d45d9fd15ab6d56468677af6bf852d`
- Manifest SHA-256: `18cb802d154205f41e398b9bfe0bdbe814acd1bb4e40ee1b5572c4f75490ba10`

## 4. Leakage Verification

- Scenario overlap between train/validation/test: none — PASS
- Seed overlap between train/validation/test: none — PASS
- Forbidden feature check: `fault_state`, `fault_type`, label severity, `scenario_id`, and
  `scenario_label` are absent; differing label metadata produces the same typed sample — PASS
- Test set frozen: PASS; SHA-256
  `906ad912bbe0b03d689e9e6d7ff7b9383ea7ae71a1e322b55d9b7d90c81bc460`
- Selection discipline: features, algorithms, anomaly threshold, and uncertainty threshold used
  train/validation only. The first formal evaluation attempt stopped before metrics due an index
  shape error; after a tiny-fixture regression fix, the unchanged frozen evaluation completed.

## 5. Feature Pipeline

- Window: 20 ticks
- Inference/dataset stride: 5 samples
- Feature count: 76
- Feature version: `features-v1`
- Features: nine bounded statistics for eight signals plus four cross-signal features
- Invalid handling: missing/irregular, insufficient, NaN, infinity, and out-of-range windows are
  rejected explicitly; no `fillna(0)` behavior exists.

## 6. Model Comparison

| Model | Purpose | Validation Metrics | Selected |
|---|---|---:|---|
| Deterministic rules | Classification baseline | Macro F1 0.4861 | No |
| Logistic Regression | Classification baseline | Macro F1 0.9639 | No |
| Decision Tree | Classification baseline | Macro F1 0.9842 | No |
| Random Forest + sigmoid calibration | Fault classifier | Macro F1 0.9981 | Yes |
| Robust normal statistics | Anomaly detector | PR-AUC 0.8664; F1 0.6667; FPR 3.5928% | Yes |
| Isolation Forest | Anomaly detector baseline | PR-AUC 0.6893; F1 0.3420; FPR 4.7904% | No |

The Isolation Forest used normal training windows only. Final artifact:
`diagnosis-v1`, SHA-256
`043b88b4ab996c673996a3f6a9cc847a79a589dfc93f021dff9cca58d9b8167f`.

## 7. Final Test Metrics

### Anomaly

- PR-AUC: 0.8763 — PASS
- ROC-AUC: 0.9074
- Precision: 0.8831
- Recall: 0.5551
- F1: 0.6817
- Normal FPR: 0.051842 — FAIL (target ≤ 0.05)

### Fault classification on held-out fault windows

- Accuracy: 1.0000
- Balanced accuracy: 1.0000
- Macro F1: 1.0000 — PASS
- Weighted F1: 1.0000
- Per-class recall: BEARING_WEAR 1.0000; OVERLOAD 1.0000; OVERHEATING 1.0000;
  MISALIGNMENT 1.0000; SENSOR_FAILURE 1.0000 — PASS

Classification metrics evaluate the classifier separately from anomaly gating. The end-to-end
anomaly recall remains 0.5551 and is not hidden by the perfect synthetic class separation.

## 8. Calibration

- Method: sigmoid `CalibratedClassifierCV`, scenario-group three-fold training splits
- Multiclass Brier score: 0.003232
- ECE (10 bins): 0.021269
- UNCERTAIN threshold: 0.60, selected on validation only
- Frozen-test uncertainty rate: 0.3868%

## 9. Detection Delay

- Mean: 13.29 ticks
- Median: 13 ticks
- P95: 22.65 ticks
- Detected fault scenarios: 28
- Missed scenarios: 7, all SENSOR_FAILURE scenarios

## 10. Confusion Matrix

Rows are truth; columns are prediction.

| Truth | BEARING_WEAR | OVERLOAD | OVERHEATING | MISALIGNMENT | SENSOR_FAILURE |
|---|---:|---:|---:|---:|---:|
| BEARING_WEAR | 127 | 0 | 0 | 0 | 0 |
| OVERLOAD | 0 | 112 | 0 | 0 | 0 |
| OVERHEATING | 0 | 0 | 29 | 0 | 0 |
| MISALIGNMENT | 0 | 0 | 0 | 121 | 0 |
| SENSOR_FAILURE | 0 | 0 | 0 | 0 | 128 |

There was no BEARING_WEAR/MISALIGNMENT or OVERLOAD/OVERHEATING confusion in the held-out
classifier evaluation. This reflects separable simulator patterns and is not a real-world claim.

## 11. Error Analysis

- Anomaly false positives: 38; all 38 were post-label recovery windows with residual physical
  heat or vibration. These caused the FPR miss and were retained.
- Anomaly false negatives: 230 windows, concentrated in early/weak ramps.
- Low-severity false negatives (scenario severity < 0.70): 24.
- Fault classifier confusions: 0.
- Sensor-failure classifier confusions: 0; however anomaly gating missed all fault windows in 7
  SENSOR_FAILURE scenarios, so the end-to-end limitation remains material.
- Full examples: `docs/evaluation/ERROR_ANALYSIS.md`.

## 12. Online Integration

| Link | Result |
|---|---|
| Simulator | PASS |
| MQTT | PASS |
| Backend ingestion | PASS |
| Bounded window / stride | PASS |
| Final artifact load and SHA match | PASS |
| Online model inference | PASS |
| Diagnosis PostgreSQL persistence | PASS |
| History/latest REST APIs | PASS |
| Restart warmup from PostgreSQL | PASS |
| Missing-model explicit readiness failure | PASS |

The final run sent 470 simulator samples and persisted 91 diagnoses. After backend restart, the
20-point window was restored; five additional samples produced diagnosis 92. A separate instance
with a missing artifact returned readiness 503 with `diagnosis=unavailable` while MQTT remained
connected. No fallback result was fabricated.

## 13. Live Fault Tests

- NORMAL: 7/7 diagnoses NORMAL; maximum anomaly score 0.2364.
- BEARING_WEAR: 17 expected fault diagnoses; best confidence 0.9856, CRITICAL; evidence included
  vibration 29.27 mm/s and bearing temperature 216.89 °C; final five recovery diagnoses NORMAL.
- OVERLOAD: 5 expected fault diagnoses; best confidence 0.9851, CRITICAL; evidence included load
  120%, current 13.17 A, and power 7.67 kW; final five recovery diagnoses NORMAL.
- MISALIGNMENT: 16 expected fault diagnoses; best confidence 0.9857, CRITICAL; evidence included
  vibration 18.55 mm/s; three transition windows were classified OVERLOAD; final five recovery
  diagnoses NORMAL.

## 14. Regression

- Backend pytest: PASS — 10 tests
- ML pytest: PASS — 13 tests
- Simulator pytest: PASS — 24 tests
- Frontend Vitest: PASS — 1 test
- Ruff: PASS (backend, ML, simulator, Phase 3 gate)
- mypy strict: PASS (backend, ML, simulator)
- Frontend ESLint/build: PASS
- Docker: PASS (Compose validation and pinned-dependency backend/simulator builds)
- Alembic: PASS (`20260917_02 (head)`; no schema drift)

## 15. Security / Dependency

- Added pinned serving/training dependencies: NumPy 2.2.6, scikit-learn 1.6.1, joblib 1.4.2.
- Container `pip check`: PASS.
- Artifact is SHA-256 checked before deserialization and checked for model, feature, telemetry
  schema, and exact library compatibility.
- No new secrets, external model calls, LLMs, RAG, or write access to industrial controls.
- Existing frontend audit remains open: four Vite/esbuild development-chain advisories (two
  moderate, one high, one critical); the offered automated fix is a breaking Vite upgrade and is
  outside the Phase 3 ML scope.
- The host-global Python environment has unrelated pre-existing OpenTelemetry package conflicts;
  the isolated backend container has no broken requirements.

## 16. Known Limitations

- Synthetic-to-real: results prove the simulator benchmark and engineering lifecycle only.
- No concurrent/multi-fault scenarios and no real sensor/domain-shift validation.
- Anomaly FPR misses the target by 0.184 percentage points; recovery hysteresis is not modeled.
- Anomaly recall is 55.51%, with seven missed sensor-failure scenarios.
- 760 physically invalid generated windows were rejected and reported, reducing OVERHEATING
  representation; they were not silently filled or relabeled.
- Severity is a transparent heuristic, not a separately validated prognostic model.
- Exact confidence and thresholds require revalidation for any new equipment or schema.

## 17. Git Diff

- Files changed from Phase 2 baseline `d7e1dd0`: 45
- Insertions: 6,253
- Deletions: 29
- Raw generated datasets and intermediate output remain gitignored; the selected deployment
  artifact is under 1 MB and tracked with its manifest.

## 18. Phase 4 Readiness

**NOT_READY**
