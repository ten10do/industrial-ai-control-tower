# PHASE_3_1_FINAL_REPORT

## 1. Status

**PASS**

Phase 3.1 closes the only failed Phase 3 gate without tuning against the exposed test. The
one-shot blind acceptance passed every required gate, the real online chain passed, and regression
checks passed. The original Phase 3 report remains **PARTIAL**, with `EXPOSED_TEST_V1` Normal FPR
**5.1842% (38/733)** preserved as engineering history.

## 2. Exposed Test V1 root cause

All 38 Normal false positives were audited with scenario ID, seed, window ticks, anomaly score,
threshold, raw signal summaries, and robust-z feature evidence in
`docs/evaluation/EXPOSED_TEST_V1_ANALYSIS.md`.

- Recovery-window overlap: 34
- Post-recovery residual physical state: 4
- High-load Normal regime: 16, overlapping the recovery categories
- Within 10% above the threshold: 14
- Isolation Forest behavior: not causal; the selected detector is robust statistical

The Normal test tail was modestly heavier than validation. The old threshold was also selected
against a point-estimate FPR constraint with little generalization margin. This is a recovery-boundary
and tail-margin issue, not evidence that a more complex detector is required.

| Split / label | n | Mean | Median | P90 | P95 | P99 | Max |
|---|---:|---:|---:|---:|---:|---:|---:|
| Normal validation | 668 | 9.102 | 2.038 | 33.803 | 42.638 | 61.814 | 89.496 |
| Normal exposed test | 733 | 9.955 | 2.361 | 35.801 | 45.977 | 60.725 | 97.885 |
| Fault validation | 448 | 55.826 | 49.981 | 104.957 | 108.991 | 178.245 | 208.740 |
| Fault exposed test | 517 | 56.958 | 53.776 | 112.184 | 125.500 | 192.957 | 210.613 |

## 3. Validation-only operating point

The model family and training data are unchanged. The deterministic selection rule maximizes
validation anomaly recall, tie-breaks by F1 and lower FPR, and requires the two-sided Wilson 95%
upper bound of validation Normal FPR to be at most 5%.

- Old threshold: 45.887684
- New threshold: 46.708485
- Validation Normal FPR: 3.143713% (21/668)
- Validation Normal FPR Wilson 95% upper bound: 4.758024%
- Validation anomaly recall: 0.515625
- Previous validation anomaly recall: 0.526786
- Validation PR-AUC: 0.866384, unchanged

This creates a statistical margin using validation only. `EXPOSED_TEST_V1` was not used to select
the new threshold and was not rerun as a final acceptance set.

## 4. Classification audit

- Label leakage: none. `fault_state`, `fault_type`, severity label, scenario ID, seed, and fault
  configuration are absent from the 76-feature runtime schema.
- Scenario overlap: none across train, validation, exposed test, and blind scenarios.
- Seed overlap: none across original and blind scenarios.
- Runtime parity: the audit uses the same `features-v1` extraction path as online inference.
- Synthetic separability: confirmed. A nearest-training-centroid audit reached 0.905222 accuracy
  on exposed fault windows without label metadata.

The original Macro F1 of 1.0000 is reproducible within the synthetic benchmark, but the simulator
uses class-specific signal templates that are easier to separate than real industrial faults. It
must not be interpreted as real-world diagnostic accuracy. Details are preserved in
`docs/evaluation/SYNTHETIC_SEPARABILITY_AUDIT.md`.

## 5. Frozen blind holdout

- Dataset version: `motor-sim-blind-v1`
- Scenario count: 120; 20 for each of six classes
- Normal scenarios: 20
- Accepted windows: 3,948
- Explicitly rejected invalid windows: 492
- New seed verification: 120 blind seeds versus 200 original seeds; overlap 0
- Manifest SHA-256: `16d8b3772e709b184a094bd8e886f3ca2199afbeca69bfbffe91ce52795ead00`
- Holdout SHA-256: `e95de69f462313c2217ac085bdd73531dbed84d3dda3cee0cedaf05dfafdb936`
- Frozen label/feature SHA-256: `baff0970a70bac76f9639a4fb705b90e745b009a2fd1173ed179353298662c22`

The configuration and seed plan were fixed in commit `7fa15ef`; the manifest and final artifact
were frozen together in commit `8166143`. Label-based blind metrics were then revealed exactly
once. The manifest writer now returns the already-frozen document and refuses a different holdout,
preventing accidental timestamp or hash replacement.

## 6. One-shot blind acceptance

### Anomaly metrics

- PR-AUC: 0.890698 — PASS (target >= 0.85)
- ROC-AUC: 0.914195
- Precision: 0.951136
- Recall: 0.506352
- F1: 0.660876
- Normal false positives: 43
- Normal windows: 2,295
- Normal FPR: 1.873638% — PASS (target <= 5%)
- Normal FPR Wilson 95% CI: [1.393976%, 2.514143%]

### Fault classification

- Accuracy: 0.911676
- Balanced accuracy: 0.902245
- Macro F1: 0.914032 — PASS (target >= 0.80)
- Weighted F1: 0.915830
- Minimum per-class recall: 0.839623, OVERHEATING — PASS (target >= 0.70)
- Other recalls: BEARING_WEAR 0.912935; OVERLOAD 0.986264; MISALIGNMENT 0.880299;
  SENSOR_FAILURE 0.892105

### Detection delay and trade-off

- Mean: 15.6203 ticks
- Median: 14 ticks
- P95: 28 ticks
- Detected fault scenarios: 79
- Missed fault scenarios: 21

Compared with exposed Test V1, mean delay increased by 2.33 ticks, median by 1 tick, and P95 by
5.35 ticks. Recall moved from 0.5551 to 0.5064 and F1 from 0.6817 to 0.6609. This is a modest,
explicit cost of the conservative operating point rather than a hidden recall collapse. All 20
SENSOR_FAILURE scenarios were missed by anomaly gating; this remains a material limitation even
though classifier-only recall is high.

## 7. Real online chain

The rebuilt `diagnosis-v1.1` container passed the complete chain:

`IndustrialMotor -> MQTT -> Backend -> Window -> Model -> PostgreSQL -> REST`

- Readiness: PostgreSQL ok, Redis ok, MQTT connected, diagnosis loaded
- Input: 470 real simulator telemetry messages
- Output: 91 persisted diagnosis rows, verified through REST and PostgreSQL
- NORMAL: 7/7 diagnoses NORMAL
- BEARING_WEAR: 17 matching fault diagnoses; final five recovery diagnoses NORMAL
- OVERLOAD: 5 matching fault diagnoses; final five recovery diagnoses NORMAL
- MISALIGNMENT: 16 matching fault diagnoses; final five recovery diagnoses NORMAL
- Restart warmup: PASS; five messages after restart produced diagnosis 92 from restored history
- Missing model: PASS; isolated instance returned HTTP 503 with `diagnosis=unavailable` while MQTT
  remained connected; no fallback diagnosis was fabricated
- Alembic: `20260917_02 (head)` and no schema drift

## 8. Artifact identity

- Version: `diagnosis-v1.1`
- Parent version: `diagnosis-v1`
- SHA-256: `acc96cf3b380a34aa4bf471dbdd9d6193e51e9a3d19d295cde08591580d07dc1`
- Feature version: `features-v1`
- Training dataset version: `motor-sim-v1`
- Blind dataset version: `motor-sim-blind-v1`
- Old `diagnosis-v1` SHA-256 remains unchanged:
  `043b88b4ab996c673996a3f6a9cc847a79a589dfc93f021dff9cca58d9b8167f`

Both hashes were rechecked inside the built backend image.

## 9. Regression and dependency checks

- Backend: Ruff, formatting, mypy strict, and 10 pytest tests — PASS
- ML: Ruff, formatting, mypy strict, and 16 pytest tests — PASS
- Simulator: Ruff, formatting, mypy strict, and 24 pytest tests — PASS
- Frontend: ESLint, 1 Vitest test, and production build — PASS
- Integration gate script: Ruff — PASS
- Docker Compose validation and backend/simulator builds — PASS
- Alembic current/check — PASS
- Container `pip check` — PASS
- `git diff --check` — PASS

The existing frontend development-chain audit remains open: four Vite/esbuild advisories (two
moderate, one high, one critical). The automated remediation is a breaking Vite upgrade and is not
introduced into this narrowly scoped model-acceptance change.

## 10. Limitations

- All benchmark data are synthetic; no real motor, site, or sensor-domain validation exists.
- Fault templates remain more separable than real faults, despite the blind set's wider load,
  severity, timing, ramp, duration, and recovery ranges.
- Recovery windows account for all 43 blind false positives.
- There are no concurrent/multi-fault scenarios.
- Anomaly gating remains weak for SENSOR_FAILURE and low-severity/early-ramp windows.
- Confidence, threshold, and delay require fresh validation before deployment to new equipment.

## 11. Phase 4 readiness

**READY**

The required one-shot blind gates passed, no leakage or regression was found, and the deployed
artifact passed the real online chain. Phase 4 is ready to begin, but this task stops here and does
not implement or start Phase 4.
