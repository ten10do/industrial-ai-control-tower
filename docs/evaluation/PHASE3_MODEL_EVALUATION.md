# Phase 3 Model Evaluation

## Scope and limitation

This is a **synthetic industrial motor diagnosis benchmark**. It proves the ML engineering
pipeline and performance on held-out simulator scenarios. It does not demonstrate equivalent
accuracy on real motors, sensors, environments, or failure mechanisms.

## Dataset and split

- Dataset: `motor-sim-v1`
- Test scenarios: 43
- Test windows: 1250
- Split unit: scenario and globally unique seed (no row-level random split)
- Frozen test hash: `906ad912bbe0b03d689e9e6d7ff7b9383ea7ae71a1e322b55d9b7d90c81bc460`
- Feature schema: `features-v1`, 76 features, 20-tick window, stride 5
- Forbidden label fields are excluded by the typed feature boundary and mandatory leakage test.

## Validation-only model selection

| Model | Purpose | Validation metric | Selected |
|---|---|---|---|
| decision_tree | fault classification | macro F1=0.9842 | no |
| deterministic_rules | fault classification | macro F1=0.4861 | no |
| logistic_regression | fault classification | macro F1=0.9639 | no |
| random_forest | fault classification | macro F1=0.9981 | yes |

| Anomaly model | Validation metrics | Selected |
|---|---|---|
| isolation_forest | PR-AUC=0.6893; F1=0.3420 | no |
| robust_statistical | PR-AUC=0.8664; F1=0.6667 | yes |

All thresholds, model selection, feature decisions, and confidence tuning used train/validation
only. This report is the single evaluation of the frozen test split.

## Final anomaly test metrics

- Precision: 0.8831
- Recall: 0.5551
- F1: 0.6817
- ROC-AUC: 0.9074
- PR-AUC: 0.8763
- Normal false-positive rate: 0.0518

## Final fault-classification test metrics

- Accuracy: 1.0000
- Balanced accuracy: 1.0000
- Macro F1: 1.0000
- Weighted F1: 1.0000

| Class | Precision | Recall | F1 |
|---|---|---|---|
| BEARING_WEAR | 1.0000 | 1.0000 | 1.0000 |
| OVERLOAD | 1.0000 | 1.0000 | 1.0000 |
| OVERHEATING | 1.0000 | 1.0000 | 1.0000 |
| MISALIGNMENT | 1.0000 | 1.0000 | 1.0000 |
| SENSOR_FAILURE | 1.0000 | 1.0000 | 1.0000 |

## Confusion matrix

Rows are truth and columns are predictions.

| Truth | BEARING_WEAR | OVERLOAD | OVERHEATING | MISALIGNMENT | SENSOR_FAILURE |
|---|---|---|---|---|---|
| BEARING_WEAR | 127 | 0 | 0 | 0 | 0 |
| OVERLOAD | 0 | 112 | 0 | 0 | 0 |
| OVERHEATING | 0 | 0 | 29 | 0 | 0 |
| MISALIGNMENT | 0 | 0 | 0 | 121 | 0 |
| SENSOR_FAILURE | 0 | 0 | 0 | 0 | 128 |

The largest confusion pairs are recorded in `ERROR_ANALYSIS.md`, including the requested
BEARING_WEAR/MISALIGNMENT and OVERLOAD/OVERHEATING checks.

## Calibration and uncertainty

- Method: sigmoid calibration with scenario-group training folds
- Multiclass Brier score: 0.0032
- Expected calibration error (10 bins): 0.0213
- UNCERTAIN threshold: 0.6000
- Test uncertainty rate: 0.0039

## Detection delay

- Mean: 13.285714285714286 ticks
- Median: 13.0 ticks
- P95: 22.65 ticks
- Detected scenarios: 28
- Missed scenarios: 7

## Acceptance targets

```json
{
  "anomaly_pr_auc_gte_0_85": true,
  "classification_macro_f1_gte_0_80": true,
  "minimum_recall_gte_0_70": true,
  "normal_fpr_lte_0_05": false
}
```

Overall targets met: **False**

## Limitations

- Simulator labels describe synthetic injected scenarios, not verified real-world root causes.
- Faults are single-fault scenarios; concurrent faults are outside this benchmark.
- Sensor failure covers deterministic stuck/intermittent-spike behavior, not every sensor mode.
- Confidence calibration and thresholds require revalidation after domain or sensor changes.
- No LLM, RAG, agent workflow, or automated maintenance action participates in diagnosis.
