# Phase 3 Error Analysis

This report intentionally records failures rather than filtering difficult windows.

## False positives

- Count: 38
- Examples: `[{"scenario_id": "bearing_wear-001", "window_end_tick": 129, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-001", "window_end_tick": 134, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-006", "window_end_tick": 139, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-006", "window_end_tick": 144, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-006", "window_end_tick": 149, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-014", "window_end_tick": 139, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-016", "window_end_tick": 124, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-016", "window_end_tick": 129, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-016", "window_end_tick": 134, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-026", "window_end_tick": 139, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-026", "window_end_tick": 144, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-026", "window_end_tick": 149, "truth": "NORMAL"}]`

## False negatives

- Count: 230
- Examples: `[{"scenario_id": "bearing_wear-001", "window_end_tick": 44, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-001", "window_end_tick": 49, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-006", "window_end_tick": 44, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-006", "window_end_tick": 49, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-012", "window_end_tick": 59, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-012", "window_end_tick": 64, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-012", "window_end_tick": 69, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-012", "window_end_tick": 74, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-014", "window_end_tick": 44, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-014", "window_end_tick": 49, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-014", "window_end_tick": 54, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-014", "window_end_tick": 59, "truth": "BEARING_WEAR"}]`

## Fault confusion

- Count: 0
- Pairs: `{}`

## Low-severity failures

- False negatives below scenario severity 0.70: 24
- Examples: `[{"scenario_id": "bearing_wear-012", "window_end_tick": 59, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-012", "window_end_tick": 64, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-012", "window_end_tick": 69, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-012", "window_end_tick": 74, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-014", "window_end_tick": 44, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-014", "window_end_tick": 49, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-014", "window_end_tick": 54, "truth": "BEARING_WEAR"}, {"scenario_id": "bearing_wear-014", "window_end_tick": 59, "truth": "BEARING_WEAR"}, {"scenario_id": "overheating-017", "window_end_tick": 59, "truth": "OVERHEATING"}, {"scenario_id": "overheating-017", "window_end_tick": 64, "truth": "OVERHEATING"}, {"scenario_id": "overheating-027", "window_end_tick": 39, "truth": "OVERHEATING"}, {"scenario_id": "overheating-027", "window_end_tick": 44, "truth": "OVERHEATING"}]`

## Recovery phase

- Post-recovery false positives: 38
- Examples: `[{"scenario_id": "bearing_wear-001", "window_end_tick": 129, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-001", "window_end_tick": 134, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-006", "window_end_tick": 139, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-006", "window_end_tick": 144, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-006", "window_end_tick": 149, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-014", "window_end_tick": 139, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-016", "window_end_tick": 124, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-016", "window_end_tick": 129, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-016", "window_end_tick": 134, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-026", "window_end_tick": 139, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-026", "window_end_tick": 144, "truth": "NORMAL"}, {"scenario_id": "bearing_wear-026", "window_end_tick": 149, "truth": "NORMAL"}]`

## Sensor failure edge cases

- Classification confusions: 0
- Examples: `[]`

## Interpretation

Residual thermal/mechanical state after the injected label ends can legitimately remain abnormal;
these recovery false positives are retained. Low-severity ramps are the expected source of missed
early windows. Confusion pairs should be interpreted against overlapping simulated signal
patterns, not removed or relabeled after seeing test results.
