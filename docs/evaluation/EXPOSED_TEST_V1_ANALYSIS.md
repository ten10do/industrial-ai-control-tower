# EXPOSED_TEST_V1 Normal False-Positive Analysis

This report preserves the immutable Phase 3 result. It is diagnostic evidence only and is not a
new acceptance run.

- Model: `diagnosis-v1`
- Artifact: `043b88b4ab996c673996a3f6a9cc847a79a589dfc93f021dff9cca58d9b8167f`
- Threshold: 45.887684
- Normal windows: 733
- False positives: 38
- Normal FPR: 5.184175%
- Wilson 95% CI: [3.800042%, 7.035594%]

## Score distributions

| Group | N | Mean | Median | P90 | P95 | P99 | Max | ≥ threshold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| normal_validation | 668 | 9.102 | 2.038 | 33.803 | 42.638 | 61.814 | 89.496 | 24 |
| normal_exposed_test | 733 | 9.955 | 2.361 | 35.801 | 45.977 | 60.725 | 97.885 | 38 |
| fault_validation | 448 | 55.826 | 49.981 | 104.957 | 108.991 | 178.245 | 208.740 | 236 |
| fault_exposed_test | 517 | 56.958 | 53.776 | 112.184 | 125.500 | 192.957 | 210.613 | 287 |

## Root cause

All Test V1 false positives occur in scenarios that previously contained an injected fault. The
simulator label returns to NORMAL when the fault envelope ends, while motor temperature,
bearing temperature, vibration, load, or window history can remain physically displaced. This
is recovery contamination / residual state, not random NORMAL-only scenario variance. Threshold
tail placement contributes: the original rule optimized validation F1 with only a point-estimate
FPR ≤5%, providing no sampling margin. The selected detector is robust statistics, so Isolation
Forest behavior is not causal.

Cause counts: `{"high_load_normal_regime": 16, "post_recovery_residual_state": 4, "recovery_window_overlap": 34, "threshold_proximity_within_10pct": 14}`

## All 38 false positives

Signal columns are window means. Full last values and top robust-z feature vectors follow in JSON.

| Scenario | Seed | Ticks | Score | Margin | Load | Motor T | Bearing T | Vib | A | RPM | Causes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| bearing_wear-001 | 202609211 | 110–129 | 65.468 | 19.580 | 40.29 | 97.20 | 172.06 | 17.49 | 4.02 | 1451.4 | recovery_window_overlap |
| bearing_wear-001 | 202609211 | 115–134 | 52.210 | 6.323 | 40.36 | 91.63 | 152.74 | 11.99 | 4.02 | 1451.0 | recovery_window_overlap |
| bearing_wear-006 | 202609216 | 120–139 | 97.885 | 51.998 | 64.02 | 121.54 | 217.02 | 23.78 | 6.41 | 1422.8 | recovery_window_overlap |
| bearing_wear-006 | 202609216 | 125–144 | 65.193 | 19.305 | 64.25 | 116.03 | 197.50 | 17.77 | 6.43 | 1422.2 | recovery_window_overlap |
| bearing_wear-006 | 202609216 | 130–149 | 54.877 | 8.990 | 64.48 | 108.44 | 173.02 | 11.59 | 6.45 | 1421.5 | recovery_window_overlap |
| bearing_wear-014 | 202609224 | 120–139 | 56.109 | 10.222 | 47.92 | 85.52 | 143.57 | 14.91 | 4.78 | 1442.9 | recovery_window_overlap |
| bearing_wear-016 | 202609226 | 105–124 | 82.878 | 36.990 | 36.75 | 103.09 | 188.40 | 20.74 | 3.66 | 1456.0 | recovery_window_overlap |
| bearing_wear-016 | 202609226 | 110–129 | 59.469 | 13.581 | 36.05 | 97.77 | 169.58 | 15.02 | 3.58 | 1456.5 | recovery_window_overlap |
| bearing_wear-016 | 202609226 | 115–134 | 47.292 | 1.405 | 35.55 | 90.64 | 146.97 | 9.51 | 3.54 | 1457.3 | recovery_window_overlap, threshold_proximity_within_10pct |
| bearing_wear-026 | 202609236 | 120–139 | 89.918 | 44.030 | 67.27 | 125.73 | 222.11 | 22.65 | 6.70 | 1420.2 | recovery_window_overlap |
| bearing_wear-026 | 202609236 | 125–144 | 66.769 | 20.881 | 67.03 | 118.68 | 198.33 | 15.95 | 6.71 | 1420.6 | recovery_window_overlap |
| bearing_wear-026 | 202609236 | 130–149 | 53.449 | 7.561 | 66.82 | 109.99 | 171.68 | 9.89 | 6.68 | 1420.0 | recovery_window_overlap |
| bearing_wear-027 | 202609237 | 120–139 | 61.315 | 15.428 | 44.34 | 102.32 | 176.88 | 16.66 | 4.42 | 1447.0 | recovery_window_overlap |
| bearing_wear-027 | 202609237 | 125–144 | 50.792 | 4.904 | 44.36 | 95.79 | 155.83 | 11.18 | 4.44 | 1446.3 | recovery_window_overlap |
| overload-001 | 202609243 | 125–144 | 49.012 | 3.124 | 112.51 | 188.93 | 208.05 | 3.45 | 11.28 | 1368.2 | recovery_window_overlap, high_load_normal_regime, threshold_proximity_within_10pct |
| overload-001 | 202609243 | 130–149 | 46.573 | 0.685 | 110.31 | 171.20 | 196.63 | 3.45 | 11.02 | 1368.5 | recovery_window_overlap, high_load_normal_regime, threshold_proximity_within_10pct |
| overload-002 | 202609244 | 140–159 | 50.689 | 4.801 | 109.39 | 178.37 | 212.85 | 3.45 | 10.93 | 1369.2 | post_recovery_residual_state, high_load_normal_regime |
| overload-003 | 202609245 | 125–144 | 46.399 | 0.511 | 111.22 | 175.44 | 196.55 | 3.46 | 11.15 | 1367.0 | recovery_window_overlap, high_load_normal_regime, threshold_proximity_within_10pct |
| overload-005 | 202609247 | 120–139 | 57.406 | 11.519 | 110.93 | 199.17 | 225.84 | 3.45 | 11.14 | 1366.5 | recovery_window_overlap, high_load_normal_regime |
| overload-005 | 202609247 | 125–144 | 51.068 | 5.180 | 109.13 | 178.68 | 210.70 | 3.44 | 10.93 | 1368.5 | post_recovery_residual_state, high_load_normal_regime |
| overload-012 | 202609254 | 120–139 | 54.819 | 8.931 | 113.58 | 213.88 | 231.55 | 3.44 | 11.54 | 1367.5 | recovery_window_overlap, high_load_normal_regime |
| overload-012 | 202609254 | 125–144 | 54.892 | 9.005 | 110.82 | 193.78 | 219.97 | 3.44 | 11.14 | 1368.0 | recovery_window_overlap, high_load_normal_regime |
| overload-012 | 202609254 | 130–149 | 48.711 | 2.824 | 109.41 | 174.17 | 205.16 | 3.44 | 10.98 | 1368.3 | post_recovery_residual_state, high_load_normal_regime, threshold_proximity_within_10pct |
| overload-026 | 202609268 | 125–144 | 47.992 | 2.104 | 117.70 | 228.64 | 227.83 | 3.46 | 12.59 | 1362.8 | recovery_window_overlap, high_load_normal_regime, threshold_proximity_within_10pct |
| overload-026 | 202609268 | 130–149 | 46.078 | 0.190 | 115.12 | 215.46 | 224.95 | 3.46 | 11.86 | 1365.7 | recovery_window_overlap, high_load_normal_regime, threshold_proximity_within_10pct |
| overload-026 | 202609268 | 135–154 | 52.428 | 6.540 | 112.51 | 197.73 | 217.11 | 3.46 | 11.31 | 1367.8 | recovery_window_overlap, high_load_normal_regime |
| overload-026 | 202609268 | 140–159 | 49.932 | 4.044 | 110.22 | 178.72 | 205.18 | 3.45 | 11.01 | 1369.1 | recovery_window_overlap, high_load_normal_regime, threshold_proximity_within_10pct |
| overload-031 | 202609273 | 125–144 | 45.911 | 0.023 | 114.54 | 203.82 | 216.65 | 3.45 | 11.68 | 1366.4 | recovery_window_overlap, high_load_normal_regime, threshold_proximity_within_10pct |
| overload-031 | 202609273 | 130–149 | 49.768 | 3.881 | 111.80 | 186.50 | 207.78 | 3.45 | 11.22 | 1367.7 | recovery_window_overlap, high_load_normal_regime, threshold_proximity_within_10pct |
| overload-031 | 202609273 | 135–154 | 46.222 | 0.334 | 109.53 | 168.58 | 195.50 | 3.45 | 10.95 | 1368.2 | recovery_window_overlap, high_load_normal_regime, threshold_proximity_within_10pct |
| overheating-011 | 202609285 | 145–164 | 47.257 | 1.369 | 45.12 | 145.31 | 192.64 | 2.47 | 4.49 | 1446.3 | post_recovery_residual_state, threshold_proximity_within_10pct |
| misalignment-015 | 202609321 | 115–134 | 53.770 | 7.882 | 65.48 | 83.11 | 85.04 | 14.44 | 6.73 | 1422.0 | recovery_window_overlap |
| misalignment-018 | 202609324 | 110–129 | 74.215 | 28.327 | 37.85 | 87.74 | 89.27 | 18.79 | 4.06 | 1455.2 | recovery_window_overlap |
| misalignment-018 | 202609324 | 115–134 | 50.460 | 4.573 | 38.02 | 84.17 | 88.66 | 14.05 | 3.96 | 1455.0 | recovery_window_overlap, threshold_proximity_within_10pct |
| misalignment-022 | 202609328 | 115–134 | 51.346 | 5.458 | 56.09 | 86.23 | 89.84 | 14.24 | 5.78 | 1433.2 | recovery_window_overlap |
| misalignment-024 | 202609330 | 120–139 | 52.737 | 6.849 | 50.43 | 86.77 | 90.32 | 14.69 | 5.23 | 1440.5 | recovery_window_overlap |
| misalignment-025 | 202609331 | 115–134 | 56.362 | 10.474 | 60.34 | 90.33 | 93.37 | 15.40 | 6.21 | 1426.6 | recovery_window_overlap |
| misalignment-028 | 202609334 | 120–139 | 49.343 | 3.456 | 56.09 | 78.40 | 80.73 | 13.43 | 5.77 | 1432.2 | recovery_window_overlap, threshold_proximity_within_10pct |

## Full feature evidence

```json
[
  {
    "anomaly_score": 65.46775934169715,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "BEARING_WEAR",
    "scenario_id": "bearing_wear-001",
    "scenario_severity": 0.806,
    "seed": 202609211,
    "signals": {
      "bearing_temperature_c": {
        "last": 130.15,
        "mean": 172.056
      },
      "current_a": {
        "last": 4.0,
        "mean": 4.024500000000001
      },
      "load_pct": {
        "last": 40.0,
        "mean": 40.290000000000006
      },
      "rpm": {
        "last": 1452.0,
        "mean": 1451.4
      },
      "temperature_c": {
        "last": 85.07,
        "mean": 97.203
      },
      "vibration_mm_s": {
        "last": 5.58,
        "mean": 17.494
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 19.580075741697627,
    "top_anomaly_features": [
      {
        "abs_robust_z": 65.46775934169715,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 18.27
      },
      {
        "abs_robust_z": 62.16486240388502,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 17.494
      },
      {
        "abs_robust_z": 58.97053132406637,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 74.853
      },
      {
        "abs_robust_z": 54.91223926080928,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 26.74
      },
      {
        "abs_robust_z": 54.488680739370324,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 7.193380568272472
      },
      {
        "abs_robust_z": 53.213434997492776,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 21.159999999999997
      },
      {
        "abs_robust_z": 36.03614012602138,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 21.904991075095193
      },
      {
        "abs_robust_z": 33.98639244073044,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 66.28999999999999
      }
    ],
    "window_end_tick": 129,
    "window_start_tick": 110
  },
  {
    "anomaly_score": 52.21043095696269,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "BEARING_WEAR",
    "scenario_id": "bearing_wear-001",
    "scenario_severity": 0.806,
    "seed": 202609211,
    "signals": {
      "bearing_temperature_c": {
        "last": 111.07,
        "mean": 152.73600000000002
      },
      "current_a": {
        "last": 4.12,
        "mean": 4.0235
      },
      "load_pct": {
        "last": 40.8,
        "mean": 40.364999999999995
      },
      "rpm": {
        "last": 1450.0,
        "mean": 1451.05
      },
      "temperature_c": {
        "last": 78.11,
        "mean": 91.62849999999999
      },
      "vibration_mm_s": {
        "last": 3.45,
        "mean": 11.99
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 6.32274735696317,
    "top_anomaly_features": [
      {
        "abs_robust_z": 52.21043095696269,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 6.893041418706259
      },
      {
        "abs_robust_z": 51.75208119547831,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 20.580000000000002
      },
      {
        "abs_robust_z": 48.69878755321876,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 24.03
      },
      {
        "abs_robust_z": 47.6793156235718,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 61.1075
      },
      {
        "abs_robust_z": 43.593543701837454,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 26.47578561629475
      },
      {
        "abs_robust_z": 41.42091578714023,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 80.71000000000001
      },
      {
        "abs_robust_z": 38.962380277890155,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 11.99
      },
      {
        "abs_robust_z": 34.54657358694192,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 10.934999999999999
      }
    ],
    "window_end_tick": 134,
    "window_start_tick": 115
  },
  {
    "anomaly_score": 97.88547146904106,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "BEARING_WEAR",
    "scenario_id": "bearing_wear-006",
    "scenario_severity": 0.9328,
    "seed": 202609216,
    "signals": {
      "bearing_temperature_c": {
        "last": 173.98,
        "mean": 217.0185
      },
      "current_a": {
        "last": 6.41,
        "mean": 6.411499999999999
      },
      "load_pct": {
        "last": 64.4,
        "mean": 64.02
      },
      "rpm": {
        "last": 1425.0,
        "mean": 1422.85
      },
      "temperature_c": {
        "last": 109.61,
        "mean": 121.53800000000001
      },
      "vibration_mm_s": {
        "last": 9.98,
        "mean": 23.779500000000002
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 51.997787869041545,
    "top_anomaly_features": [
      {
        "abs_robust_z": 97.88547146904106,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 25.96
      },
      {
        "abs_robust_z": 88.66181033319837,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 23.779500000000002
      },
      {
        "abs_robust_z": 75.9149532702998,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 95.48049999999999
      },
      {
        "abs_robust_z": 64.19802502307557,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 30.79
      },
      {
        "abs_robust_z": 52.56360888795643,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 6.939600474811212
      },
      {
        "abs_robust_z": 52.33158356524267,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 20.81
      },
      {
        "abs_robust_z": 32.5517385558192,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 19.79758956918746
      },
      {
        "abs_robust_z": 31.50649942434827,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 61.48000000000002
      }
    ],
    "window_end_tick": 139,
    "window_start_tick": 120
  },
  {
    "anomaly_score": 65.19286913941198,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "BEARING_WEAR",
    "scenario_id": "bearing_wear-006",
    "scenario_severity": 0.9328,
    "seed": 202609216,
    "signals": {
      "bearing_temperature_c": {
        "last": 146.34,
        "mean": 197.4975
      },
      "current_a": {
        "last": 6.46,
        "mean": 6.427
      },
      "load_pct": {
        "last": 64.6,
        "mean": 64.255
      },
      "rpm": {
        "last": 1424.0,
        "mean": 1422.25
      },
      "temperature_c": {
        "last": 100.15,
        "mean": 116.03249999999998
      },
      "vibration_mm_s": {
        "last": 5.12,
        "mean": 17.771500000000003
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 19.305185539412463,
    "top_anomaly_features": [
      {
        "abs_robust_z": 65.19286913941198,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 8.604501888546483
      },
      {
        "abs_robust_z": 64.40194656626709,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 81.46499999999999
      },
      {
        "abs_robust_z": 64.22416700391217,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 17.975
      },
      {
        "abs_robust_z": 63.82084793970133,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 25.369999999999997
      },
      {
        "abs_robust_z": 63.51018904068547,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 30.49
      },
      {
        "abs_robust_z": 63.33468231485225,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 17.771500000000003
      },
      {
        "abs_robust_z": 48.30070523604246,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 29.322724783860043
      },
      {
        "abs_robust_z": 45.653747734021245,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 88.91999999999999
      }
    ],
    "window_end_tick": 144,
    "window_start_tick": 125
  },
  {
    "anomaly_score": 54.87747048321651,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "BEARING_WEAR",
    "scenario_id": "bearing_wear-006",
    "scenario_severity": 0.9328,
    "seed": 202609216,
    "signals": {
      "bearing_temperature_c": {
        "last": 126.39,
        "mean": 173.02450000000002
      },
      "current_a": {
        "last": 6.37,
        "mean": 6.45
      },
      "load_pct": {
        "last": 64.6,
        "mean": 64.48499999999999
      },
      "rpm": {
        "last": 1420.0,
        "mean": 1421.45
      },
      "temperature_c": {
        "last": 91.98,
        "mean": 108.4425
      },
      "vibration_mm_s": {
        "last": 3.54,
        "mean": 11.591999999999999
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 8.989786883216993,
    "top_anomaly_features": [
      {
        "abs_robust_z": 54.87747048321651,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 7.244634290286847
      },
      {
        "abs_robust_z": 54.624397289092975,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 21.720000000000002
      },
      {
        "abs_robust_z": 51.67926650691102,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 31.366113000338437
      },
      {
        "abs_robust_z": 51.51891508101815,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 25.26
      },
      {
        "abs_robust_z": 50.5334372598432,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 64.58200000000001
      },
      {
        "abs_robust_z": 49.89689108637579,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 97.14999999999999
      },
      {
        "abs_robust_z": 37.28458451369213,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 11.591999999999999
      },
      {
        "abs_robust_z": 27.464420612437657,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 9.254999999999999
      }
    ],
    "window_end_tick": 149,
    "window_start_tick": 130
  },
  {
    "anomaly_score": 56.10920005395937,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "BEARING_WEAR",
    "scenario_id": "bearing_wear-014",
    "scenario_severity": 0.5574,
    "seed": 202609224,
    "signals": {
      "bearing_temperature_c": {
        "last": 117.97,
        "mean": 143.56900000000002
      },
      "current_a": {
        "last": 4.91,
        "mean": 4.775499999999999
      },
      "load_pct": {
        "last": 49.2,
        "mean": 47.915000000000006
      },
      "rpm": {
        "last": 1441.0,
        "mean": 1442.9
      },
      "temperature_c": {
        "last": 78.34,
        "mean": 85.52199999999999
      },
      "vibration_mm_s": {
        "last": 6.79,
        "mean": 14.9115
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 10.22151645395985,
    "top_anomaly_features": [
      {
        "abs_robust_z": 56.10920005395937,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 16.05
      },
      {
        "abs_robust_z": 51.27815998920811,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 14.9115
      },
      {
        "abs_robust_z": 45.1652735260589,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 58.047000000000004
      },
      {
        "abs_robust_z": 37.44120530810086,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 19.12
      },
      {
        "abs_robust_z": 31.124087588001053,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 4.1132520892840985
      },
      {
        "abs_robust_z": 30.96558314958269,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 12.330000000000002
      },
      {
        "abs_robust_z": 19.35177498800126,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 11.814117360175496
      },
      {
        "abs_robust_z": 18.71004523170673,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 36.66
      }
    ],
    "window_end_tick": 139,
    "window_start_tick": 120
  },
  {
    "anomaly_score": 82.87805207068678,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "BEARING_WEAR",
    "scenario_id": "bearing_wear-016",
    "scenario_severity": 0.8637,
    "seed": 202609226,
    "signals": {
      "bearing_temperature_c": {
        "last": 146.66,
        "mean": 188.4035
      },
      "current_a": {
        "last": 3.53,
        "mean": 3.6620000000000004
      },
      "load_pct": {
        "last": 35.3,
        "mean": 36.754999999999995
      },
      "rpm": {
        "last": 1455.0,
        "mean": 1455.95
      },
      "temperature_c": {
        "last": 91.21,
        "mean": 103.08949999999997
      },
      "vibration_mm_s": {
        "last": 7.7,
        "mean": 20.7395
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 36.99036847068726,
    "top_anomaly_features": [
      {
        "abs_robust_z": 82.87805207068678,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 22.4
      },
      {
        "abs_robust_z": 75.84648590314306,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 20.7395
      },
      {
        "abs_robust_z": 67.5637005389275,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 85.31400000000001
      },
      {
        "abs_robust_z": 58.236779842361415,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 28.19
      },
      {
        "abs_robust_z": 52.221211570187265,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 6.894462615026642
      },
      {
        "abs_robust_z": 51.525319398613995,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 20.490000000000002
      },
      {
        "abs_robust_z": 32.546814929651894,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 19.794611710008358
      },
      {
        "abs_robust_z": 31.38791826140275,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 61.25
      }
    ],
    "window_end_tick": 124,
    "window_start_tick": 105
  },
  {
    "anomaly_score": 59.46903822876625,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "BEARING_WEAR",
    "scenario_id": "bearing_wear-016",
    "scenario_severity": 0.8637,
    "seed": 202609226,
    "signals": {
      "bearing_temperature_c": {
        "last": 122.88,
        "mean": 169.58050000000003
      },
      "current_a": {
        "last": 3.51,
        "mean": 3.5835
      },
      "load_pct": {
        "last": 35.3,
        "mean": 36.05499999999999
      },
      "rpm": {
        "last": 1457.0,
        "mean": 1456.45
      },
      "temperature_c": {
        "last": 82.94,
        "mean": 97.771
      },
      "vibration_mm_s": {
        "last": 4.11,
        "mean": 15.022500000000003
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 13.581354628766732,
    "top_anomaly_features": [
      {
        "abs_robust_z": 59.46903822876625,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 7.849935588907721
      },
      {
        "abs_robust_z": 58.10141150767915,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 23.1
      },
      {
        "abs_robust_z": 56.470453845294756,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 71.8095
      },
      {
        "abs_robust_z": 55.989848966553765,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 27.21
      },
      {
        "abs_robust_z": 51.746087953595,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 15.022500000000003
      },
      {
        "abs_robust_z": 51.02944152165125,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 14.844999999999999
      },
      {
        "abs_robust_z": 45.46789843731779,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 27.60941442243932
      },
      {
        "abs_robust_z": 42.90060247259073,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 83.58000000000001
      }
    ],
    "window_end_tick": 129,
    "window_start_tick": 110
  },
  {
    "anomaly_score": 47.292432523813424,
    "causes": [
      "recovery_window_overlap",
      "threshold_proximity_within_10pct"
    ],
    "scenario_fault_type": "BEARING_WEAR",
    "scenario_id": "bearing_wear-016",
    "scenario_severity": 0.8637,
    "seed": 202609226,
    "signals": {
      "bearing_temperature_c": {
        "last": 105.67,
        "mean": 146.9675
      },
      "current_a": {
        "last": 3.62,
        "mean": 3.535
      },
      "load_pct": {
        "last": 35.1,
        "mean": 35.545
      },
      "rpm": {
        "last": 1457.0,
        "mean": 1457.35
      },
      "temperature_c": {
        "last": 75.98,
        "mean": 90.6385
      },
      "vibration_mm_s": {
        "last": 2.91,
        "mean": 9.512
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 1.404748923813905,
    "top_anomaly_features": [
      {
        "abs_robust_z": 47.292432523813424,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 18.81
      },
      {
        "abs_robust_z": 47.07874167736977,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 6.216536495509376
      },
      {
        "abs_robust_z": 46.800942840690674,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 28.41565323461701
      },
      {
        "abs_robust_z": 45.31862705613176,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 88.27
      },
      {
        "abs_robust_z": 43.754025585027314,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 56.32900000000001
      },
      {
        "abs_robust_z": 43.40245048881501,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 21.72
      },
      {
        "abs_robust_z": 28.516204640496404,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 9.512
      },
      {
        "abs_robust_z": 21.015977174937134,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 9.36579109045253
      }
    ],
    "window_end_tick": 134,
    "window_start_tick": 115
  },
  {
    "anomaly_score": 89.91804937272376,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "BEARING_WEAR",
    "scenario_id": "bearing_wear-026",
    "scenario_severity": 0.9931,
    "seed": 202609236,
    "signals": {
      "bearing_temperature_c": {
        "last": 170.23,
        "mean": 222.11299999999997
      },
      "current_a": {
        "last": 6.64,
        "mean": 6.7015
      },
      "load_pct": {
        "last": 66.9,
        "mean": 67.27
      },
      "rpm": {
        "last": 1427.0,
        "mean": 1420.2
      },
      "temperature_c": {
        "last": 110.49,
        "mean": 125.7325
      },
      "vibration_mm_s": {
        "last": 7.7,
        "mean": 22.647000000000002
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 44.03036577272424,
    "top_anomaly_features": [
      {
        "abs_robust_z": 89.91804937272376,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 24.07
      },
      {
        "abs_robust_z": 83.8876804262781,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 22.647000000000002
      },
      {
        "abs_robust_z": 76.65425661542695,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 96.3805
      },
      {
        "abs_robust_z": 68.53139171213317,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 32.68
      },
      {
        "abs_robust_z": 63.977404503247946,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 8.44426852960042
      },
      {
        "abs_robust_z": 62.838213486622635,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 24.98
      },
      {
        "abs_robust_z": 43.00646398044527,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 26.120713830215283
      },
      {
        "abs_robust_z": 40.75583013409803,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 79.42000000000002
      }
    ],
    "window_end_tick": 139,
    "window_start_tick": 120
  },
  {
    "anomaly_score": 66.7686497273904,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "BEARING_WEAR",
    "scenario_id": "bearing_wear-026",
    "scenario_severity": 0.9931,
    "seed": 202609236,
    "signals": {
      "bearing_temperature_c": {
        "last": 144.32,
        "mean": 198.3315
      },
      "current_a": {
        "last": 6.68,
        "mean": 6.707000000000001
      },
      "load_pct": {
        "last": 66.2,
        "mean": 67.025
      },
      "rpm": {
        "last": 1422.0,
        "mean": 1420.6
      },
      "temperature_c": {
        "last": 100.93,
        "mean": 118.68050000000001
      },
      "vibration_mm_s": {
        "last": 4.4,
        "mean": 15.947
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 20.880966127390877,
    "top_anomaly_features": [
      {
        "abs_robust_z": 66.7686497273904,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 8.812235300989187
      },
      {
        "abs_robust_z": 65.73572533544446,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 26.130000000000003
      },
      {
        "abs_robust_z": 63.60190050500415,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 30.53
      },
      {
        "abs_robust_z": 62.911839601755304,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 79.65100000000002
      },
      {
        "abs_robust_z": 55.64337987319569,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 15.947
      },
      {
        "abs_robust_z": 54.813514098872766,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 33.261737819151904
      },
      {
        "abs_robust_z": 52.56812356670724,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 15.21
      },
      {
        "abs_robust_z": 51.98495069476412,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 101.20000000000002
      }
    ],
    "window_end_tick": 144,
    "window_start_tick": 125
  },
  {
    "anomaly_score": 53.449138092464004,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "BEARING_WEAR",
    "scenario_id": "bearing_wear-026",
    "scenario_severity": 0.9931,
    "seed": 202609236,
    "signals": {
      "bearing_temperature_c": {
        "last": 125.79,
        "mean": 171.68350000000004
      },
      "current_a": {
        "last": 6.46,
        "mean": 6.678
      },
      "load_pct": {
        "last": 65.6,
        "mean": 66.82000000000001
      },
      "rpm": {
        "last": 1419.0,
        "mean": 1420.0
      },
      "temperature_c": {
        "last": 92.77,
        "mean": 109.989
      },
      "vibration_mm_s": {
        "last": 3.31,
        "mean": 9.893
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 7.561454492464485,
    "top_anomaly_features": [
      {
        "abs_robust_z": 53.449138092464004,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 32.43654933481674
      },
      {
        "abs_robust_z": 52.36647269728444,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 101.93999999999998
      },
      {
        "abs_robust_z": 50.1647486174281,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 19.950000000000003
      },
      {
        "abs_robust_z": 49.256519983374695,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 6.503630601441014
      },
      {
        "abs_robust_z": 48.16150569422694,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 61.69449999999999
      },
      {
        "abs_robust_z": 46.93334186508418,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 23.26
      },
      {
        "abs_robust_z": 30.122335761500047,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 9.893
      },
      {
        "abs_robust_z": 24.810019684125354,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 11.035623181316044
      }
    ],
    "window_end_tick": 149,
    "window_start_tick": 130
  },
  {
    "anomaly_score": 61.31542560366935,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "BEARING_WEAR",
    "scenario_id": "bearing_wear-027",
    "scenario_severity": 0.8195,
    "seed": 202609237,
    "signals": {
      "bearing_temperature_c": {
        "last": 132.13,
        "mean": 176.87900000000002
      },
      "current_a": {
        "last": 4.43,
        "mean": 4.422
      },
      "load_pct": {
        "last": 44.2,
        "mean": 44.34
      },
      "rpm": {
        "last": 1450.0,
        "mean": 1447.0
      },
      "temperature_c": {
        "last": 88.42,
        "mean": 102.3195
      },
      "vibration_mm_s": {
        "last": 5.04,
        "mean": 16.662
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 15.427742003669827,
    "top_anomaly_features": [
      {
        "abs_robust_z": 61.31542560366935,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 17.285
      },
      {
        "abs_robust_z": 58.72943628873881,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 74.55950000000001
      },
      {
        "abs_robust_z": 58.65751045460672,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 16.662
      },
      {
        "abs_robust_z": 56.13675292095066,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 7.410644101560943
      },
      {
        "abs_robust_z": 55.30201298416367,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 26.91
      },
      {
        "abs_robust_z": 55.002333617200165,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 21.87
      },
      {
        "abs_robust_z": 40.51036889962483,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 24.611050140130143
      },
      {
        "abs_robust_z": 38.327494145083456,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 74.71000000000001
      }
    ],
    "window_end_tick": 139,
    "window_start_tick": 120
  },
  {
    "anomaly_score": 50.792116280038925,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "BEARING_WEAR",
    "scenario_id": "bearing_wear-027",
    "scenario_severity": 0.8195,
    "seed": 202609237,
    "signals": {
      "bearing_temperature_c": {
        "last": 113.54,
        "mean": 155.834
      },
      "current_a": {
        "last": 4.57,
        "mean": 4.4430000000000005
      },
      "load_pct": {
        "last": 43.7,
        "mean": 44.355000000000004
      },
      "rpm": {
        "last": 1447.0,
        "mean": 1446.3
      },
      "temperature_c": {
        "last": 81.08,
        "mean": 95.79499999999999
      },
      "vibration_mm_s": {
        "last": 3.31,
        "mean": 11.182500000000001
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 4.904432680039406,
    "top_anomaly_features": [
      {
        "abs_robust_z": 50.792116280038925,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 6.7060665631948515
      },
      {
        "abs_robust_z": 50.1647486174281,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 19.950000000000003
      },
      {
        "abs_robust_z": 46.93334186508418,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 23.26
      },
      {
        "abs_robust_z": 46.80159826327364,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 60.03900000000001
      },
      {
        "abs_robust_z": 45.660099943189906,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 27.72565984787377
      },
      {
        "abs_robust_z": 43.715203504998996,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 85.15999999999998
      },
      {
        "abs_robust_z": 35.55830972615673,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 11.182500000000001
      },
      {
        "abs_robust_z": 28.771246458923567,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 9.565
      }
    ],
    "window_end_tick": 144,
    "window_start_tick": 125
  },
  {
    "anomaly_score": 49.01173625452849,
    "causes": [
      "recovery_window_overlap",
      "high_load_normal_regime",
      "threshold_proximity_within_10pct"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-001",
    "scenario_severity": 0.7541,
    "seed": 202609243,
    "signals": {
      "bearing_temperature_c": {
        "last": 184.55,
        "mean": 208.05450000000002
      },
      "current_a": {
        "last": 10.96,
        "mean": 11.283500000000002
      },
      "load_pct": {
        "last": 110.0,
        "mean": 112.51499999999999
      },
      "rpm": {
        "last": 1365.0,
        "mean": 1368.2
      },
      "temperature_c": {
        "last": 154.64,
        "mean": 188.9295
      },
      "vibration_mm_s": {
        "last": 3.46,
        "mean": 3.4515000000000002
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 3.124052654528974,
    "top_anomaly_features": [
      {
        "abs_robust_z": 49.01173625452849,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 21.68727056939162
      },
      {
        "abs_robust_z": 47.266818716818186,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 67.80000000000001
      },
      {
        "abs_robust_z": 21.39815665938018,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 222.09
      },
      {
        "abs_robust_z": 20.119473662930695,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 211.0
      },
      {
        "abs_robust_z": 19.85369887431832,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 12.11768603116948
      },
      {
        "abs_robust_z": 19.794129540926864,
        "name": "bearing_temperature_c__mean",
        "robust_center": 51.239999999999995,
        "robust_scale": 7.9222730999999875,
        "value": 208.05450000000002
      },
      {
        "abs_robust_z": 19.6031644349722,
        "name": "temperature_c__max",
        "robust_center": 48.93,
        "robust_scale": 8.851121999999998,
        "value": 222.44
      },
      {
        "abs_robust_z": 19.16374707254172,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 37.53999999999999
      }
    ],
    "window_end_tick": 144,
    "window_start_tick": 125
  },
  {
    "anomaly_score": 46.57254348640794,
    "causes": [
      "recovery_window_overlap",
      "high_load_normal_regime",
      "threshold_proximity_within_10pct"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-001",
    "scenario_severity": 0.7541,
    "seed": 202609243,
    "signals": {
      "bearing_temperature_c": {
        "last": 169.63,
        "mean": 196.62600000000003
      },
      "current_a": {
        "last": 11.01,
        "mean": 11.022
      },
      "load_pct": {
        "last": 109.8,
        "mean": 110.31499999999998
      },
      "rpm": {
        "last": 1361.0,
        "mean": 1368.45
      },
      "temperature_c": {
        "last": 140.63,
        "mean": 171.199
      },
      "vibration_mm_s": {
        "last": 3.45,
        "mean": 3.4510000000000005
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 0.6848598864084181,
    "top_anomaly_features": [
      {
        "abs_robust_z": 46.57254348640794,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 66.81
      },
      {
        "abs_robust_z": 46.24548604448024,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 20.46978991098834
      },
      {
        "abs_robust_z": 25.545808372994763,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 15.560331744535528
      },
      {
        "abs_robust_z": 25.164985058131872,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 49.18000000000001
      },
      {
        "abs_robust_z": 20.986942962152813,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 218.81
      },
      {
        "abs_robust_z": 18.471348249718513,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 197.91500000000002
      },
      {
        "abs_robust_z": 18.369634506006317,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 25.427000000000003
      },
      {
        "abs_robust_z": 18.351551147611946,
        "name": "bearing_temperature_c__mean",
        "robust_center": 51.239999999999995,
        "robust_scale": 7.9222730999999875,
        "value": 196.62600000000003
      }
    ],
    "window_end_tick": 149,
    "window_start_tick": 130
  },
  {
    "anomaly_score": 50.68910470106256,
    "causes": [
      "post_recovery_residual_state",
      "high_load_normal_regime"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-002",
    "scenario_severity": 0.9651,
    "seed": 202609244,
    "signals": {
      "bearing_temperature_c": {
        "last": 178.73,
        "mean": 212.85399999999998
      },
      "current_a": {
        "last": 10.91,
        "mean": 10.929499999999999
      },
      "load_pct": {
        "last": 108.7,
        "mean": 109.38999999999999
      },
      "rpm": {
        "last": 1374.0,
        "mean": 1369.15
      },
      "temperature_c": {
        "last": 145.52,
        "mean": 178.36599999999996
      },
      "vibration_mm_s": {
        "last": 3.45,
        "mean": 3.4505000000000003
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 4.801421101063042,
    "top_anomaly_features": [
      {
        "abs_robust_z": 50.68910470106256,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 72.67999999999998
      },
      {
        "abs_robust_z": 49.68573140789316,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 21.983908979069216
      },
      {
        "abs_robust_z": 34.63601098556237,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 67.55000000000001
      },
      {
        "abs_robust_z": 34.452051635483535,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 20.946918245890018
      },
      {
        "abs_robust_z": 25.812776295114116,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 34.488
      },
      {
        "abs_robust_z": 24.430857676432012,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 246.28
      },
      {
        "abs_robust_z": 20.39995313971191,
        "name": "bearing_temperature_c__mean",
        "robust_center": 51.239999999999995,
        "robust_scale": 7.9222730999999875,
        "value": 212.85399999999998
      },
      {
        "abs_robust_z": 20.358159001718395,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 212.89499999999998
      }
    ],
    "window_end_tick": 159,
    "window_start_tick": 140
  },
  {
    "anomaly_score": 46.399100518396516,
    "causes": [
      "recovery_window_overlap",
      "high_load_normal_regime",
      "threshold_proximity_within_10pct"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-003",
    "scenario_severity": 0.7056,
    "seed": 202609245,
    "signals": {
      "bearing_temperature_c": {
        "last": 172.48,
        "mean": 196.5455
      },
      "current_a": {
        "last": 10.91,
        "mean": 11.147499999999999
      },
      "load_pct": {
        "last": 108.9,
        "mean": 111.225
      },
      "rpm": {
        "last": 1365.0,
        "mean": 1367.05
      },
      "temperature_c": {
        "last": 143.99,
        "mean": 175.43649999999997
      },
      "vibration_mm_s": {
        "last": 3.46,
        "mean": 3.4555
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 0.5114169183969963,
    "top_anomaly_features": [
      {
        "abs_robust_z": 46.399100518396516,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 20.537398636390154
      },
      {
        "abs_robust_z": 45.37334081569934,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 65.1
      },
      {
        "abs_robust_z": 21.3994752138917,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 13.052587281838035
      },
      {
        "abs_robust_z": 20.78779343462153,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 40.69
      },
      {
        "abs_robust_z": 20.279855994969168,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 213.17
      },
      {
        "abs_robust_z": 18.585967594466165,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 198.825
      },
      {
        "abs_robust_z": 18.341389922546373,
        "name": "bearing_temperature_c__mean",
        "robust_center": 51.239999999999995,
        "robust_scale": 7.9222730999999875,
        "value": 196.5455
      },
      {
        "abs_robust_z": 18.094881078353684,
        "name": "temperature_c__max",
        "robust_center": 48.93,
        "robust_scale": 8.851121999999998,
        "value": 209.09
      }
    ],
    "window_end_tick": 144,
    "window_start_tick": 125
  },
  {
    "anomaly_score": 57.40634668617009,
    "causes": [
      "recovery_window_overlap",
      "high_load_normal_regime"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-005",
    "scenario_severity": 0.9015,
    "seed": 202609247,
    "signals": {
      "bearing_temperature_c": {
        "last": 195.36,
        "mean": 225.839
      },
      "current_a": {
        "last": 10.77,
        "mean": 11.136
      },
      "load_pct": {
        "last": 109.0,
        "mean": 110.92500000000003
      },
      "rpm": {
        "last": 1363.0,
        "mean": 1366.55
      },
      "temperature_c": {
        "last": 160.69,
        "mean": 199.16500000000002
      },
      "vibration_mm_s": {
        "last": 3.43,
        "mean": 3.4509999999999996
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 11.51866308617057,
    "top_anomaly_features": [
      {
        "abs_robust_z": 57.40634668617009,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 25.381902312474534
      },
      {
        "abs_robust_z": 56.65706653014451,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 81.19
      },
      {
        "abs_robust_z": 27.755598807717156,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 16.89683547295173
      },
      {
        "abs_robust_z": 27.015882340629165,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 52.76999999999998
      },
      {
        "abs_robust_z": 24.66279223127062,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 248.13
      },
      {
        "abs_robust_z": 22.278977691170883,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 228.145
      },
      {
        "abs_robust_z": 22.03900292202755,
        "name": "bearing_temperature_c__mean",
        "robust_center": 51.239999999999995,
        "robust_scale": 7.9222730999999875,
        "value": 225.839
      },
      {
        "abs_robust_z": 21.799496154272873,
        "name": "temperature_c__max",
        "robust_center": 48.93,
        "robust_scale": 8.851121999999998,
        "value": 241.88
      }
    ],
    "window_end_tick": 139,
    "window_start_tick": 120
  },
  {
    "anomaly_score": 51.067800281286345,
    "causes": [
      "post_recovery_residual_state",
      "high_load_normal_regime"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-005",
    "scenario_severity": 0.9015,
    "seed": 202609247,
    "signals": {
      "bearing_temperature_c": {
        "last": 178.44,
        "mean": 210.69699999999997
      },
      "current_a": {
        "last": 10.82,
        "mean": 10.931999999999999
      },
      "load_pct": {
        "last": 108.3,
        "mean": 109.12500000000003
      },
      "rpm": {
        "last": 1374.0,
        "mean": 1368.5
      },
      "temperature_c": {
        "last": 145.78,
        "mean": 178.6765
      },
      "vibration_mm_s": {
        "last": 3.4,
        "mean": 3.4395000000000002
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 5.180116681286826,
    "top_anomaly_features": [
      {
        "abs_robust_z": 51.067800281286345,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 73.22
      },
      {
        "abs_robust_z": 50.19011322403473,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 22.205897251631146
      },
      {
        "abs_robust_z": 31.95504556244649,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 62.349999999999994
      },
      {
        "abs_robust_z": 31.868232622504394,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 19.384198229485786
      },
      {
        "abs_robust_z": 23.78585295722388,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 32.02050000000001
      },
      {
        "abs_robust_z": 23.74257621369474,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 240.79
      },
      {
        "abs_robust_z": 20.14592428094938,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 211.20999999999998
      },
      {
        "abs_robust_z": 20.12768279851401,
        "name": "bearing_temperature_c__mean",
        "robust_center": 51.239999999999995,
        "robust_scale": 7.9222730999999875,
        "value": 210.69699999999997
      }
    ],
    "window_end_tick": 144,
    "window_start_tick": 125
  },
  {
    "anomaly_score": 54.81889812081798,
    "causes": [
      "recovery_window_overlap",
      "high_load_normal_regime"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-012",
    "scenario_severity": 0.8539,
    "seed": 202609254,
    "signals": {
      "bearing_temperature_c": {
        "last": 207.2,
        "mean": 231.55499999999998
      },
      "current_a": {
        "last": 10.97,
        "mean": 11.5365
      },
      "load_pct": {
        "last": 109.2,
        "mean": 113.575
      },
      "rpm": {
        "last": 1365.0,
        "mean": 1367.5
      },
      "temperature_c": {
        "last": 174.04,
        "mean": 213.87699999999995
      },
      "vibration_mm_s": {
        "last": 3.44,
        "mean": 3.441
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 8.931214520818457,
    "top_anomaly_features": [
      {
        "abs_robust_z": 54.81889812081798,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 24.243115744474757
      },
      {
        "abs_robust_z": 52.11271956745933,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 74.71000000000001
      },
      {
        "abs_robust_z": 30.599157992111735,
        "name": "current_a__std",
        "robust_center": 0.09344918405208255,
        "robust_scale": 0.019270813959356377,
        "value": 0.6831198650310206
      },
      {
        "abs_robust_z": 30.224890276551402,
        "name": "power_kw__std",
        "robust_center": 0.056169386679934444,
        "robust_scale": 0.011223754017075784,
        "value": 0.395406120337053
      },
      {
        "abs_robust_z": 24.097373397582988,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 243.62
      },
      {
        "abs_robust_z": 23.21356619449793,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 235.565
      },
      {
        "abs_robust_z": 22.76051301488209,
        "name": "bearing_temperature_c__mean",
        "robust_center": 51.239999999999995,
        "robust_scale": 7.9222730999999875,
        "value": 231.55499999999998
      },
      {
        "abs_robust_z": 22.575668937791168,
        "name": "temperature_c__max",
        "robust_center": 48.93,
        "robust_scale": 8.851121999999998,
        "value": 248.75
      }
    ],
    "window_end_tick": 139,
    "window_start_tick": 120
  },
  {
    "anomaly_score": 54.89222453157626,
    "causes": [
      "recovery_window_overlap",
      "high_load_normal_regime"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-012",
    "scenario_severity": 0.8539,
    "seed": 202609254,
    "signals": {
      "bearing_temperature_c": {
        "last": 190.25,
        "mean": 219.96600000000004
      },
      "current_a": {
        "last": 10.9,
        "mean": 11.140500000000001
      },
      "load_pct": {
        "last": 109.0,
        "mean": 110.81500000000001
      },
      "rpm": {
        "last": 1367.0,
        "mean": 1368.0
      },
      "temperature_c": {
        "last": 157.02,
        "mean": 193.77749999999997
      },
      "vibration_mm_s": {
        "last": 3.44,
        "mean": 3.4435000000000002
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 9.004540931576742,
    "top_anomaly_features": [
      {
        "abs_robust_z": 54.89222453157626,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 24.275388127690153
      },
      {
        "abs_robust_z": 54.46203474106973,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 78.06
      },
      {
        "abs_robust_z": 27.245936553302464,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 16.588586558233345
      },
      {
        "abs_robust_z": 26.6137375271618,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 51.99000000000001
      },
      {
        "abs_robust_z": 23.924362756676352,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 242.24
      },
      {
        "abs_robust_z": 21.500573789478004,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 221.965
      },
      {
        "abs_robust_z": 21.297675284635204,
        "name": "bearing_temperature_c__mean",
        "robust_center": 51.239999999999995,
        "robust_scale": 7.9222730999999875,
        "value": 219.96600000000004
      },
      {
        "abs_robust_z": 21.031231972624493,
        "name": "temperature_c__max",
        "robust_center": 48.93,
        "robust_scale": 8.851121999999998,
        "value": 235.08
      }
    ],
    "window_end_tick": 144,
    "window_start_tick": 125
  },
  {
    "anomaly_score": 48.71147222656068,
    "causes": [
      "post_recovery_residual_state",
      "high_load_normal_regime",
      "threshold_proximity_within_10pct"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-012",
    "scenario_severity": 0.8539,
    "seed": 202609254,
    "signals": {
      "bearing_temperature_c": {
        "last": 174.09,
        "mean": 205.15950000000004
      },
      "current_a": {
        "last": 10.93,
        "mean": 10.976500000000001
      },
      "load_pct": {
        "last": 109.6,
        "mean": 109.405
      },
      "rpm": {
        "last": 1363.0,
        "mean": 1368.3
      },
      "temperature_c": {
        "last": 142.68,
        "mean": 174.1735
      },
      "vibration_mm_s": {
        "last": 3.44,
        "mean": 3.4430000000000005
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 2.8237886265611607,
    "top_anomaly_features": [
      {
        "abs_robust_z": 48.71147222656068,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 69.85999999999999
      },
      {
        "abs_robust_z": 47.74759821552658,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 21.130898768154655
      },
      {
        "abs_robust_z": 30.9548392315148,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 60.41
      },
      {
        "abs_robust_z": 30.871214917628773,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 18.781191781939718
      },
      {
        "abs_robust_z": 22.95399872724348,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 234.5
      },
      {
        "abs_robust_z": 22.936064834408285,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 30.985999999999997
      },
      {
        "abs_robust_z": 19.429868264586275,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 205.52499999999998
      },
      {
        "abs_robust_z": 19.428704117761388,
        "name": "bearing_temperature_c__mean",
        "robust_center": 51.239999999999995,
        "robust_scale": 7.9222730999999875,
        "value": 205.15950000000004
      }
    ],
    "window_end_tick": 149,
    "window_start_tick": 130
  },
  {
    "anomaly_score": 47.99153884292746,
    "causes": [
      "recovery_window_overlap",
      "high_load_normal_regime",
      "threshold_proximity_within_10pct"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-026",
    "scenario_severity": 0.8169,
    "seed": 202609268,
    "signals": {
      "bearing_temperature_c": {
        "last": 221.5,
        "mean": 227.83
      },
      "current_a": {
        "last": 10.92,
        "mean": 12.5945
      },
      "load_pct": {
        "last": 109.7,
        "mean": 117.7
      },
      "rpm": {
        "last": 1368.0,
        "mean": 1362.75
      },
      "temperature_c": {
        "last": 199.47,
        "mean": 228.6375
      },
      "vibration_mm_s": {
        "last": 3.47,
        "mean": 3.4575000000000005
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 2.103855242927942,
    "top_anomaly_features": [
      {
        "abs_robust_z": 47.99153884292746,
        "name": "current_a__std",
        "robust_center": 0.09344918405208255,
        "robust_scale": 0.019270813959356377,
        "value": 1.0182852007173628
      },
      {
        "abs_robust_z": 47.54965936107764,
        "name": "power_kw__std",
        "robust_center": 0.056169386679934444,
        "robust_scale": 0.011223754017075784,
        "value": 0.5898550669444147
      },
      {
        "abs_robust_z": 36.6473312648947,
        "name": "power_kw__range",
        "robust_center": 0.20999999999999996,
        "robust_scale": 0.044478000000000364,
        "value": 1.8399999999999999
      },
      {
        "abs_robust_z": 31.81348082198009,
        "name": "current_a__range",
        "robust_center": 0.35999999999999943,
        "robust_scale": 0.08895599999999809,
        "value": 3.1899999999999995
      },
      {
        "abs_robust_z": 29.48469066173592,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 13.093037033095108
      },
      {
        "abs_robust_z": 28.815928502582484,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 41.49000000000001
      },
      {
        "abs_robust_z": 24.615286426489927,
        "name": "temperature_c__median",
        "robust_center": 48.15,
        "robust_scale": 7.583499000000002,
        "value": 234.82
      },
      {
        "abs_robust_z": 24.070242866961724,
        "name": "temperature_c__mean",
        "robust_center": 48.188500000000005,
        "robust_scale": 7.49676690000001,
        "value": 228.6375
      }
    ],
    "window_end_tick": 144,
    "window_start_tick": 125
  },
  {
    "anomaly_score": 46.077510678287084,
    "causes": [
      "recovery_window_overlap",
      "high_load_normal_regime",
      "threshold_proximity_within_10pct"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-026",
    "scenario_severity": 0.8169,
    "seed": 202609268,
    "signals": {
      "bearing_temperature_c": {
        "last": 208.0,
        "mean": 224.94699999999997
      },
      "current_a": {
        "last": 10.77,
        "mean": 11.855500000000003
      },
      "load_pct": {
        "last": 109.4,
        "mean": 115.12000000000003
      },
      "rpm": {
        "last": 1370.0,
        "mean": 1365.65
      },
      "temperature_c": {
        "last": 178.65,
        "mean": 215.45850000000002
      },
      "vibration_mm_s": {
        "last": 3.46,
        "mean": 3.4579999999999997
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 0.18982707828756418,
    "top_anomaly_features": [
      {
        "abs_robust_z": 46.077510678287084,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 20.39586067686284
      },
      {
        "abs_robust_z": 43.31856664892965,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 62.16999999999999
      },
      {
        "abs_robust_z": 42.8180809006643,
        "name": "current_a__std",
        "robust_center": 0.09344918405208255,
        "robust_scale": 0.019270813959356377,
        "value": 0.9185884551854548
      },
      {
        "abs_robust_z": 41.96105666630726,
        "name": "power_kw__std",
        "robust_center": 0.056169386679934444,
        "robust_scale": 0.011223754017075784,
        "value": 0.5271299649991451
      },
      {
        "abs_robust_z": 30.576914429605385,
        "name": "power_kw__range",
        "robust_center": 0.20999999999999996,
        "robust_scale": 0.044478000000000364,
        "value": 1.5699999999999994
      },
      {
        "abs_robust_z": 26.64238499932609,
        "name": "current_a__range",
        "robust_center": 0.35999999999999943,
        "robust_scale": 0.08895599999999809,
        "value": 2.7300000000000004
      },
      {
        "abs_robust_z": 22.57796829669259,
        "name": "temperature_c__median",
        "robust_center": 48.15,
        "robust_scale": 7.583499000000002,
        "value": 219.37
      },
      {
        "abs_robust_z": 22.570366436537462,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 231.44
      }
    ],
    "window_end_tick": 149,
    "window_start_tick": 130
  },
  {
    "anomaly_score": 52.427569376176095,
    "causes": [
      "recovery_window_overlap",
      "high_load_normal_regime"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-026",
    "scenario_severity": 0.8169,
    "seed": 202609268,
    "signals": {
      "bearing_temperature_c": {
        "last": 192.51,
        "mean": 217.1065
      },
      "current_a": {
        "last": 11.06,
        "mean": 11.307500000000001
      },
      "load_pct": {
        "last": 109.4,
        "mean": 112.51000000000002
      },
      "rpm": {
        "last": 1371.0,
        "mean": 1367.8
      },
      "temperature_c": {
        "last": 160.99,
        "mean": 197.733
      },
      "vibration_mm_s": {
        "last": 3.45,
        "mean": 3.4550000000000005
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 6.539885776176575,
    "top_anomaly_features": [
      {
        "abs_robust_z": 52.427569376176095,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 23.19064533384097
      },
      {
        "abs_robust_z": 50.68910470106256,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 72.67999999999998
      },
      {
        "abs_robust_z": 22.570366436537462,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 231.44
      },
      {
        "abs_robust_z": 22.371947790788,
        "name": "current_a__std",
        "robust_center": 0.09344918405208255,
        "robust_scale": 0.019270813959356377,
        "value": 0.524574827836792
      },
      {
        "abs_robust_z": 21.29463683490392,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 220.32999999999998
      },
      {
        "abs_robust_z": 21.179136188090478,
        "name": "power_kw__std",
        "robust_center": 0.056169386679934444,
        "robust_scale": 0.011223754017075784,
        "value": 0.29387880154921003
      },
      {
        "abs_robust_z": 20.93673089861044,
        "name": "bearing_temperature_c__mean",
        "robust_center": 51.239999999999995,
        "robust_scale": 7.9222730999999875,
        "value": 217.1065
      },
      {
        "abs_robust_z": 20.87193013495916,
        "name": "temperature_c__max",
        "robust_center": 48.93,
        "robust_scale": 8.851121999999998,
        "value": 233.67
      }
    ],
    "window_end_tick": 154,
    "window_start_tick": 135
  },
  {
    "anomaly_score": 49.93171354061504,
    "causes": [
      "recovery_window_overlap",
      "high_load_normal_regime",
      "threshold_proximity_within_10pct"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-026",
    "scenario_severity": 0.8169,
    "seed": 202609268,
    "signals": {
      "bearing_temperature_c": {
        "last": 176.84,
        "mean": 205.1805
      },
      "current_a": {
        "last": 10.96,
        "mean": 11.009000000000002
      },
      "load_pct": {
        "last": 109.7,
        "mean": 110.225
      },
      "rpm": {
        "last": 1377.0,
        "mean": 1369.1
      },
      "temperature_c": {
        "last": 145.87,
        "mean": 178.72199999999998
      },
      "vibration_mm_s": {
        "last": 3.45,
        "mean": 3.4524999999999997
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 4.044029940615523,
    "top_anomaly_features": [
      {
        "abs_robust_z": 49.93171354061504,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 71.6
      },
      {
        "abs_robust_z": 49.511979168294,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 21.90743723031062
      },
      {
        "abs_robust_z": 26.820734727031002,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 16.331420169415765
      },
      {
        "abs_robust_z": 26.46937785053248,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 51.71000000000001
      },
      {
        "abs_robust_z": 22.208047050870665,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 228.55
      },
      {
        "abs_robust_z": 19.5470067158119,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 206.45499999999998
      },
      {
        "abs_robust_z": 19.431354872126313,
        "name": "bearing_temperature_c__mean",
        "robust_center": 51.239999999999995,
        "robust_scale": 7.9222730999999875,
        "value": 205.1805
      },
      {
        "abs_robust_z": 19.216958284338144,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 26.458500000000004
      }
    ],
    "window_end_tick": 159,
    "window_start_tick": 140
  },
  {
    "anomaly_score": 45.91052071260162,
    "causes": [
      "recovery_window_overlap",
      "high_load_normal_regime",
      "threshold_proximity_within_10pct"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-031",
    "scenario_severity": 0.7497,
    "seed": 202609273,
    "signals": {
      "bearing_temperature_c": {
        "last": 197.91,
        "mean": 216.647
      },
      "current_a": {
        "last": 10.82,
        "mean": 11.678
      },
      "load_pct": {
        "last": 109.7,
        "mean": 114.54499999999999
      },
      "rpm": {
        "last": 1364.0,
        "mean": 1366.4
      },
      "temperature_c": {
        "last": 168.41,
        "mean": 203.8245
      },
      "vibration_mm_s": {
        "last": 3.45,
        "mean": 3.4480000000000004
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 0.02283711260209742,
    "top_anomaly_features": [
      {
        "abs_robust_z": 45.91052071260162,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 20.322365136715753
      },
      {
        "abs_robust_z": 43.360643935621184,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 62.22999999999999
      },
      {
        "abs_robust_z": 34.65252748781212,
        "name": "power_kw__std",
        "robust_center": 0.056169386679934444,
        "robust_scale": 0.011223754017075784,
        "value": 0.44510083127309474
      },
      {
        "abs_robust_z": 34.0301018159328,
        "name": "current_a__std",
        "robust_center": 0.09344918405208255,
        "robust_scale": 0.019270813959356377,
        "value": 0.7492369451648792
      },
      {
        "abs_robust_z": 24.506497594316087,
        "name": "power_kw__range",
        "robust_center": 0.20999999999999996,
        "robust_scale": 0.044478000000000364,
        "value": 1.2999999999999998
      },
      {
        "abs_robust_z": 21.704059531707856,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 224.53
      },
      {
        "abs_robust_z": 21.684874455498463,
        "name": "load_pct__std",
        "robust_center": 0.46893496350773395,
        "robust_scale": 0.18246999715075843,
        "value": 4.425773943617092
      },
      {
        "abs_robust_z": 21.29400705828443,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 220.325
      }
    ],
    "window_end_tick": 144,
    "window_start_tick": 125
  },
  {
    "anomaly_score": 49.76837216650235,
    "causes": [
      "recovery_window_overlap",
      "high_load_normal_regime",
      "threshold_proximity_within_10pct"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-031",
    "scenario_severity": 0.7497,
    "seed": 202609273,
    "signals": {
      "bearing_temperature_c": {
        "last": 182.59,
        "mean": 207.78449999999998
      },
      "current_a": {
        "last": 10.97,
        "mean": 11.221999999999998
      },
      "load_pct": {
        "last": 108.6,
        "mean": 111.795
      },
      "rpm": {
        "last": 1371.0,
        "mean": 1367.7
      },
      "temperature_c": {
        "last": 152.34,
        "mean": 186.502
      },
      "vibration_mm_s": {
        "last": 3.45,
        "mean": 3.4465000000000003
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 3.8806885665028332,
    "top_anomaly_features": [
      {
        "abs_robust_z": 49.76837216650235,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 22.02028078840049
      },
      {
        "abs_robust_z": 48.37485393302845,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 69.38
      },
      {
        "abs_robust_z": 21.89514927738629,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 13.3523759964285
      },
      {
        "abs_robust_z": 21.661433721629408,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 224.19
      },
      {
        "abs_robust_z": 21.256962383666806,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 41.599999999999994
      },
      {
        "abs_robust_z": 20.04516002183056,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 210.41
      },
      {
        "abs_robust_z": 19.76004841337775,
        "name": "bearing_temperature_c__mean",
        "robust_center": 51.239999999999995,
        "robust_scale": 7.9222730999999875,
        "value": 207.78449999999998
      },
      {
        "abs_robust_z": 19.521818815738843,
        "name": "temperature_c__max",
        "robust_center": 48.93,
        "robust_scale": 8.851121999999998,
        "value": 221.72
      }
    ],
    "window_end_tick": 149,
    "window_start_tick": 130
  },
  {
    "anomaly_score": 46.221899430645195,
    "causes": [
      "recovery_window_overlap",
      "high_load_normal_regime",
      "threshold_proximity_within_10pct"
    ],
    "scenario_fault_type": "OVERLOAD",
    "scenario_id": "overload-031",
    "scenario_severity": 0.7497,
    "seed": 202609273,
    "signals": {
      "bearing_temperature_c": {
        "last": 167.74,
        "mean": 195.5025
      },
      "current_a": {
        "last": 10.98,
        "mean": 10.951
      },
      "load_pct": {
        "last": 108.5,
        "mean": 109.53
      },
      "rpm": {
        "last": 1371.0,
        "mean": 1368.15
      },
      "temperature_c": {
        "last": 138.54,
        "mean": 168.58350000000002
      },
      "vibration_mm_s": {
        "last": 3.44,
        "mean": 3.446
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 0.3342158306456753,
    "top_anomaly_features": [
      {
        "abs_robust_z": 46.221899430645195,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 66.31
      },
      {
        "abs_robust_z": 45.51294996737969,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 20.147386499245997
      },
      {
        "abs_robust_z": 26.789579742331647,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 16.312577317824424
      },
      {
        "abs_robust_z": 26.56733620253093,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 51.89999999999998
      },
      {
        "abs_robust_z": 21.09100008675608,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 219.64
      },
      {
        "abs_robust_z": 19.595235162594864,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 26.919
      },
      {
        "abs_robust_z": 18.281785487251227,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 196.41
      },
      {
        "abs_robust_z": 18.209735789088136,
        "name": "bearing_temperature_c__mean",
        "robust_center": 51.239999999999995,
        "robust_scale": 7.9222730999999875,
        "value": 195.5025
      }
    ],
    "window_end_tick": 154,
    "window_start_tick": 135
  },
  {
    "anomaly_score": 47.25717128515401,
    "causes": [
      "post_recovery_residual_state",
      "threshold_proximity_within_10pct"
    ],
    "scenario_fault_type": "OVERHEATING",
    "scenario_id": "overheating-011",
    "scenario_severity": 0.7402,
    "seed": 202609285,
    "signals": {
      "bearing_temperature_c": {
        "last": 150.9,
        "mean": 192.6365
      },
      "current_a": {
        "last": 4.52,
        "mean": 4.4885
      },
      "load_pct": {
        "last": 45.3,
        "mean": 45.120000000000005
      },
      "rpm": {
        "last": 1447.0,
        "mean": 1446.3
      },
      "temperature_c": {
        "last": 115.47,
        "mean": 145.312
      },
      "vibration_mm_s": {
        "last": 2.48,
        "mean": 2.466499999999999
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 1.369487685154489,
    "top_anomaly_features": [
      {
        "abs_robust_z": 47.25717128515401,
        "name": "bearing_temperature_c__range",
        "robust_center": 0.37000000000000455,
        "robust_scale": 1.9395998005660418,
        "value": 92.03
      },
      {
        "abs_robust_z": 46.22891231176044,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 66.32
      },
      {
        "abs_robust_z": 46.00856341535534,
        "name": "bearing_temperature_c__std",
        "robust_center": 0.10996704051669343,
        "robust_scale": 0.6048101699671354,
        "value": 27.936414099701487
      },
      {
        "abs_robust_z": 45.39574644790112,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 20.095802944893745
      },
      {
        "abs_robust_z": 36.35729561703027,
        "name": "bearing_motor_delta__mean",
        "robust_center": 3.0645000000000002,
        "robust_scale": 1.2173622721066193,
        "value": 47.3245
      },
      {
        "abs_robust_z": 24.010868077129672,
        "name": "bearing_temperature_c__max",
        "robust_center": 51.41,
        "robust_scale": 7.976387999999993,
        "value": 242.93
      },
      {
        "abs_robust_z": 17.84797093147423,
        "name": "bearing_temperature_c__mean",
        "robust_center": 51.239999999999995,
        "robust_scale": 7.9222730999999875,
        "value": 192.6365
      },
      {
        "abs_robust_z": 17.479450074017638,
        "name": "bearing_temperature_c__median",
        "robust_center": 51.265,
        "robust_scale": 7.939323000000005,
        "value": 190.04000000000002
      }
    ],
    "window_end_tick": 164,
    "window_start_tick": 145
  },
  {
    "anomaly_score": 53.76956023202493,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "MISALIGNMENT",
    "scenario_id": "misalignment-015",
    "scenario_severity": 0.6925,
    "seed": 202609321,
    "signals": {
      "bearing_temperature_c": {
        "last": 84.21,
        "mean": 85.04249999999999
      },
      "current_a": {
        "last": 6.78,
        "mean": 6.731
      },
      "load_pct": {
        "last": 66.4,
        "mean": 65.485
      },
      "rpm": {
        "last": 1424.0,
        "mean": 1421.95
      },
      "temperature_c": {
        "last": 77.67,
        "mean": 83.1145
      },
      "vibration_mm_s": {
        "last": 6.8,
        "mean": 14.442000000000002
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 7.88187663202541,
    "top_anomaly_features": [
      {
        "abs_robust_z": 53.76956023202493,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 15.495000000000001
      },
      {
        "abs_robust_z": 49.298951166868974,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 14.442000000000002
      },
      {
        "abs_robust_z": 36.157244807639344,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 18.56
      },
      {
        "abs_robust_z": 29.52942510277535,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 11.759999999999998
      },
      {
        "abs_robust_z": 29.44256523562283,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 3.891578856967953
      },
      {
        "abs_robust_z": 17.283825711587784,
        "name": "vibration_mm_s__min",
        "robust_center": 2.7,
        "robust_scale": 0.23721599999999954,
        "value": 6.8
      },
      {
        "abs_robust_z": 7.975638763172695,
        "name": "current_per_load__mean",
        "robust_center": 0.10003216495493653,
        "robust_scale": 0.0003460789068365983,
        "value": 0.10279236529941893
      },
      {
        "abs_robust_z": 7.91418204285577,
        "name": "power_per_load__mean",
        "robust_center": 0.05793908262332366,
        "robust_scale": 0.0002046418386582507,
        "value": 0.059558655388049775
      }
    ],
    "window_end_tick": 134,
    "window_start_tick": 115
  },
  {
    "anomaly_score": 74.21506137865924,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "MISALIGNMENT",
    "scenario_id": "misalignment-018",
    "scenario_severity": 0.9707,
    "seed": 202609324,
    "signals": {
      "bearing_temperature_c": {
        "last": 88.02,
        "mean": 89.273
      },
      "current_a": {
        "last": 3.85,
        "mean": 4.0615
      },
      "load_pct": {
        "last": 38.1,
        "mean": 37.849999999999994
      },
      "rpm": {
        "last": 1459.0,
        "mean": 1455.2
      },
      "temperature_c": {
        "last": 79.83,
        "mean": 87.7405
      },
      "vibration_mm_s": {
        "last": 8.0,
        "mean": 18.7875
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 28.327377778659724,
    "top_anomaly_features": [
      {
        "abs_robust_z": 74.21506137865924,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 20.345
      },
      {
        "abs_robust_z": 67.61769863752862,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 18.7875
      },
      {
        "abs_robust_z": 49.75346939288356,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 24.49
      },
      {
        "abs_robust_z": 41.4470173157555,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 16.49
      },
      {
        "abs_robust_z": 41.17319061004117,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 5.4380142285580675
      },
      {
        "abs_robust_z": 22.342506407662256,
        "name": "vibration_mm_s__min",
        "robust_center": 2.7,
        "robust_scale": 0.23721599999999954,
        "value": 8.0
      },
      {
        "abs_robust_z": 21.058540549133724,
        "name": "current_per_load__mean",
        "robust_center": 0.10003216495493653,
        "robust_scale": 0.0003460789068365983,
        "value": 0.1073200816477549
      },
      {
        "abs_robust_z": 21.024029998332395,
        "name": "power_per_load__mean",
        "robust_center": 0.05793908262332366,
        "robust_scale": 0.0002046418386582507,
        "value": 0.06224147877818862
      }
    ],
    "window_end_tick": 129,
    "window_start_tick": 110
  },
  {
    "anomaly_score": 50.46023076474925,
    "causes": [
      "recovery_window_overlap",
      "threshold_proximity_within_10pct"
    ],
    "scenario_fault_type": "MISALIGNMENT",
    "scenario_id": "misalignment-018",
    "scenario_severity": 0.9707,
    "seed": 202609324,
    "signals": {
      "bearing_temperature_c": {
        "last": 84.13,
        "mean": 88.6635
      },
      "current_a": {
        "last": 3.67,
        "mean": 3.9605000000000006
      },
      "load_pct": {
        "last": 37.8,
        "mean": 38.019999999999996
      },
      "rpm": {
        "last": 1453.0,
        "mean": 1454.95
      },
      "temperature_c": {
        "last": 73.39,
        "mean": 84.171
      },
      "vibration_mm_s": {
        "last": 4.23,
        "mean": 14.053999999999998
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 4.572547164749729,
    "top_anomaly_features": [
      {
        "abs_robust_z": 50.46023076474925,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 6.662314462707386
      },
      {
        "abs_robust_z": 49.53485473724944,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 19.7
      },
      {
        "abs_robust_z": 48.62656819101587,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 14.274999999999999
      },
      {
        "abs_robust_z": 48.469508892422056,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 23.93
      },
      {
        "abs_robust_z": 47.66331107513823,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 14.053999999999998
      },
      {
        "abs_robust_z": 12.834674482228873,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 5.765040242704296
      },
      {
        "abs_robust_z": 11.963975182624894,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 17.459999999999994
      },
      {
        "abs_robust_z": 11.923952528302687,
        "name": "current_per_load__mean",
        "robust_center": 0.10003216495493653,
        "robust_scale": 0.0003460789068365983,
        "value": 0.10415879341110301
      }
    ],
    "window_end_tick": 134,
    "window_start_tick": 115
  },
  {
    "anomaly_score": 51.345609065155905,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "MISALIGNMENT",
    "scenario_id": "misalignment-022",
    "scenario_severity": 0.8227,
    "seed": 202609328,
    "signals": {
      "bearing_temperature_c": {
        "last": 86.53,
        "mean": 89.83599999999998
      },
      "current_a": {
        "last": 5.64,
        "mean": 5.7780000000000005
      },
      "load_pct": {
        "last": 55.8,
        "mean": 56.089999999999996
      },
      "rpm": {
        "last": 1431.0,
        "mean": 1433.2
      },
      "temperature_c": {
        "last": 77.49,
        "mean": 86.22500000000001
      },
      "vibration_mm_s": {
        "last": 5.09,
        "mean": 14.239499999999998
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 5.457925465156386,
    "top_anomaly_features": [
      {
        "abs_robust_z": 51.345609065155905,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 14.92
      },
      {
        "abs_robust_z": 48.445298799406395,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 14.239499999999998
      },
      {
        "abs_robust_z": 42.645830908185914,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 21.39
      },
      {
        "abs_robust_z": 41.64453727981102,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 5.50015133882696
      },
      {
        "abs_robust_z": 40.96829796681973,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 16.3
      },
      {
        "abs_robust_z": 10.075205719681659,
        "name": "vibration_mm_s__min",
        "robust_center": 2.7,
        "robust_scale": 0.23721599999999954,
        "value": 5.09
      },
      {
        "abs_robust_z": 9.751494719424139,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 4.40807270811179
      },
      {
        "abs_robust_z": 9.08869392537038,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 13.36
      }
    ],
    "window_end_tick": 134,
    "window_start_tick": 115
  },
  {
    "anomaly_score": 52.73674625657639,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "MISALIGNMENT",
    "scenario_id": "misalignment-024",
    "scenario_severity": 0.9321,
    "seed": 202609330,
    "signals": {
      "bearing_temperature_c": {
        "last": 86.76,
        "mean": 90.31649999999999
      },
      "current_a": {
        "last": 5.04,
        "mean": 5.2325
      },
      "load_pct": {
        "last": 51.6,
        "mean": 50.43000000000001
      },
      "rpm": {
        "last": 1442.0,
        "mean": 1440.45
      },
      "temperature_c": {
        "last": 77.1,
        "mean": 86.77449999999999
      },
      "vibration_mm_s": {
        "last": 4.79,
        "mean": 14.688999999999997
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 6.849062656576869,
    "top_anomaly_features": [
      {
        "abs_robust_z": 52.73674625657639,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 15.25
      },
      {
        "abs_robust_z": 50.34019627681096,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 14.688999999999997
      },
      {
        "abs_robust_z": 47.76330699611237,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 6.30678198449891
      },
      {
        "abs_robust_z": 47.231404124119884,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 23.39
      },
      {
        "abs_robust_z": 46.76332166446336,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 18.6
      },
      {
        "abs_robust_z": 11.039257419650133,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 4.974842183426527
      },
      {
        "abs_robust_z": 10.87460133967569,
        "name": "current_per_load__mean",
        "robust_center": 0.10003216495493653,
        "robust_scale": 0.0003460789068365983,
        "value": 0.1037956350988553
      },
      {
        "abs_robust_z": 10.535204885993942,
        "name": "power_per_load__mean",
        "robust_center": 0.05793908262332366,
        "robust_scale": 0.0002046418386582507,
        "value": 0.060095026321834846
      }
    ],
    "window_end_tick": 139,
    "window_start_tick": 120
  },
  {
    "anomaly_score": 56.36213408876309,
    "causes": [
      "recovery_window_overlap"
    ],
    "scenario_fault_type": "MISALIGNMENT",
    "scenario_id": "misalignment-025",
    "scenario_severity": 0.9032,
    "seed": 202609331,
    "signals": {
      "bearing_temperature_c": {
        "last": 90.46,
        "mean": 93.37050000000002
      },
      "current_a": {
        "last": 5.96,
        "mean": 6.208
      },
      "load_pct": {
        "last": 60.0,
        "mean": 60.335
      },
      "rpm": {
        "last": 1428.0,
        "mean": 1426.6
      },
      "temperature_c": {
        "last": 80.97,
        "mean": 90.33099999999999
      },
      "vibration_mm_s": {
        "last": 5.41,
        "mean": 15.395500000000002
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 10.474450488763573,
    "top_anomaly_features": [
      {
        "abs_robust_z": 56.36213408876309,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 16.11
      },
      {
        "abs_robust_z": 53.31849453662482,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 15.395500000000002
      },
      {
        "abs_robust_z": 46.42892881133144,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 23.04
      },
      {
        "abs_robust_z": 45.28706336297039,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 5.9803415245285105
      },
      {
        "abs_robust_z": 44.319333409370174,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 17.63
      },
      {
        "abs_robust_z": 11.424187238634852,
        "name": "vibration_mm_s__min",
        "robust_center": 2.7,
        "robust_scale": 0.23721599999999954,
        "value": 5.41
      },
      {
        "abs_robust_z": 10.136706021270017,
        "name": "temperature_c__std",
        "robust_center": 0.11624973118248483,
        "robust_scale": 0.440119499668124,
        "value": 4.577611713546705
      },
      {
        "abs_robust_z": 9.593621365668733,
        "name": "temperature_c__range",
        "robust_center": 0.3999999999999986,
        "robust_scale": 1.4259474580636027,
        "value": 14.079999999999998
      }
    ],
    "window_end_tick": 134,
    "window_start_tick": 115
  },
  {
    "anomaly_score": 49.34321462295976,
    "causes": [
      "recovery_window_overlap",
      "threshold_proximity_within_10pct"
    ],
    "scenario_fault_type": "MISALIGNMENT",
    "scenario_id": "misalignment-028",
    "scenario_severity": 0.6417,
    "seed": 202609334,
    "signals": {
      "bearing_temperature_c": {
        "last": 79.44,
        "mean": 80.7265
      },
      "current_a": {
        "last": 5.37,
        "mean": 5.7655
      },
      "load_pct": {
        "last": 54.7,
        "mean": 56.089999999999996
      },
      "rpm": {
        "last": 1433.0,
        "mean": 1432.15
      },
      "temperature_c": {
        "last": 72.74,
        "mean": 78.3955
      },
      "vibration_mm_s": {
        "last": 6.32,
        "mean": 13.425
      }
    },
    "threshold": 45.88768359999952,
    "threshold_margin": 3.455531022960244,
    "top_anomaly_features": [
      {
        "abs_robust_z": 49.34321462295976,
        "name": "vibration_mm_s__median",
        "robust_center": 2.74,
        "robust_scale": 0.23721599999999954,
        "value": 14.445
      },
      {
        "abs_robust_z": 45.011719276945875,
        "name": "vibration_mm_s__mean",
        "robust_center": 2.7474999999999996,
        "robust_scale": 0.2372160000000002,
        "value": 13.425
      },
      {
        "abs_robust_z": 33.01612715472458,
        "name": "vibration_mm_s__max",
        "robust_center": 2.79,
        "robust_scale": 0.4361504888964354,
        "value": 17.19
      },
      {
        "abs_robust_z": 27.287002889339345,
        "name": "vibration_mm_s__range",
        "robust_center": 0.040000000000000036,
        "robust_scale": 0.3968922510075716,
        "value": 10.870000000000001
      },
      {
        "abs_robust_z": 27.16442356207995,
        "name": "vibration_mm_s__std",
        "robust_center": 0.010198039027185612,
        "robust_scale": 0.13182889421756802,
        "value": 3.5912539592738355
      },
      {
        "abs_robust_z": 15.260353433157995,
        "name": "vibration_mm_s__min",
        "robust_center": 2.7,
        "robust_scale": 0.23721599999999954,
        "value": 6.32
      },
      {
        "abs_robust_z": 7.874090683606179,
        "name": "current_per_load__mean",
        "robust_center": 0.10003216495493653,
        "robust_scale": 0.0003460789068365983,
        "value": 0.1027572216510512
      },
      {
        "abs_robust_z": 7.152815611423204,
        "name": "power_per_load__mean",
        "robust_center": 0.05793908262332366,
        "robust_scale": 0.0002046418386582507,
        "value": 0.059402847961628744
      }
    ],
    "window_end_tick": 139,
    "window_start_tick": 120
  }
]
```
