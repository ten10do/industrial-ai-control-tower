# Phase 3.1 Blind Holdout Evaluation

## Acceptance protocol

This is the first and only label-based evaluation of the frozen blind holdout. Its 120 seeds were
allocated before `diagnosis-v1.1` was trained. The model and threshold were fixed from the original
train/validation splits, then committed with the blind manifest hash before this run.

`EXPOSED_TEST_V1` remains historical evidence: Normal FPR **5.1842% (38/733)**. It was not
overwritten and was not used as the acceptance set for this version.

## Identity

- Model version: `diagnosis-v1.1`
- Parent model: `diagnosis-v1`
- Artifact SHA-256: `acc96cf3b380a34aa4bf471dbdd9d6193e51e9a3d19d295cde08591580d07dc1`
- Feature version: `features-v1`
- Training dataset: `motor-sim-v1`
- Blind dataset: `motor-sim-blind-v1`
- Blind scenarios: 120 total; 20 NORMAL
- Blind manifest SHA-256: `16d8b3772e709b184a094bd8e886f3ca2199afbeca69bfbffe91ce52795ead00`
- Blind holdout SHA-256: `e95de69f462313c2217ac085bdd73531dbed84d3dda3cee0cedaf05dfafdb936`
- New seed overlap: 0

## Validation-only operating point

- Algorithm: maximize anomaly recall; tie-break by F1 and lower FPR; require two-sided Wilson 95% Normal FPR upper bound <= 0.05
- Old threshold: 45.887684
- New threshold: 46.708485
- Validation Normal FPR: 3.143713%
- Validation FPR Wilson 95% upper: 4.758024%
- Validation anomaly recall: 0.515625

## Blind anomaly metrics

- PR-AUC: 0.890698
- ROC-AUC: 0.914195
- Precision: 0.951136
- Recall: 0.506352
- F1: 0.660876
- Normal false positives: 43
- Normal windows: 2295
- Normal FPR: 1.873638%
- Normal FPR Wilson 95% CI: [1.393976%, 2.514143%]

## Blind fault classification

- Accuracy: 0.911676
- Balanced accuracy: 0.902245
- Macro F1: 0.914032
- Weighted F1: 0.915830
- Minimum per-class recall: 0.839623

| Class | Precision | Recall | F1 |
|---|---|---|---|
| BEARING_WEAR | 1.0000 | 0.9129 | 0.9545 |
| OVERLOAD | 0.7223 | 0.9863 | 0.8339 |
| OVERHEATING | 1.0000 | 0.8396 | 0.9128 |
| MISALIGNMENT | 1.0000 | 0.8803 | 0.9363 |
| SENSOR_FAILURE | 0.9769 | 0.8921 | 0.9326 |

## Confusion matrix

| Truth | BEARING_WEAR | OVERLOAD | OVERHEATING | MISALIGNMENT | SENSOR_FAILURE |
|---|---|---|---|---|---|
| BEARING_WEAR | 367 | 35 | 0 | 0 | 0 |
| OVERLOAD | 0 | 359 | 0 | 0 | 5 |
| OVERHEATING | 0 | 17 | 89 | 0 | 0 |
| MISALIGNMENT | 0 | 45 | 0 | 353 | 3 |
| SENSOR_FAILURE | 0 | 41 | 0 | 0 | 339 |

## Detection delay

- Mean: 15.620253164556962 ticks
- Median: 14.0 ticks
- P95: 28.0 ticks
- Detected scenarios: 79
- Missed scenarios: 21

## Acceptance

```json
{
  "anomaly_pr_auc_gte_0_85": true,
  "classification_macro_f1_gte_0_80": true,
  "minimum_recall_gte_0_70": true,
  "normal_fpr_lte_0_05": true
}
```

Overall: **PASS**

## Interpretation

This remains a synthetic benchmark. Class-specific simulator templates can make classification
substantially easier than real diagnosis. The blind set widens load, severity, timing, ramp, and
recovery ranges, but it does not establish real-world generalization.
