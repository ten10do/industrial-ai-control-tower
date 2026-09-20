# Phase 3.1 Blind Error Analysis

- False positives: 43
- False negatives: 816
- Fault confusions: 146
- Low-severity false negatives: 403
- Recovery false positives: 43
- Sensor-failure confusions: 41

## Confusion pairs

```json
{
  "BEARING_WEAR -> OVERLOAD": 35,
  "MISALIGNMENT -> OVERLOAD": 45,
  "MISALIGNMENT -> SENSOR_FAILURE": 3,
  "OVERHEATING -> OVERLOAD": 17,
  "OVERLOAD -> SENSOR_FAILURE": 5,
  "SENSOR_FAILURE -> OVERLOAD": 41
}
```

## Examples

```json
{
  "false_negative_count": 816,
  "false_negative_examples": [
    {
      "scenario_id": "blind-bearing_wear-000",
      "truth": "BEARING_WEAR",
      "window_end_tick": 44
    },
    {
      "scenario_id": "blind-bearing_wear-000",
      "truth": "BEARING_WEAR",
      "window_end_tick": 49
    },
    {
      "scenario_id": "blind-bearing_wear-000",
      "truth": "BEARING_WEAR",
      "window_end_tick": 54
    },
    {
      "scenario_id": "blind-bearing_wear-000",
      "truth": "BEARING_WEAR",
      "window_end_tick": 59
    },
    {
      "scenario_id": "blind-bearing_wear-001",
      "truth": "BEARING_WEAR",
      "window_end_tick": 69
    },
    {
      "scenario_id": "blind-bearing_wear-001",
      "truth": "BEARING_WEAR",
      "window_end_tick": 74
    },
    {
      "scenario_id": "blind-bearing_wear-001",
      "truth": "BEARING_WEAR",
      "window_end_tick": 79
    },
    {
      "scenario_id": "blind-bearing_wear-001",
      "truth": "BEARING_WEAR",
      "window_end_tick": 84
    },
    {
      "scenario_id": "blind-bearing_wear-001",
      "truth": "BEARING_WEAR",
      "window_end_tick": 169
    },
    {
      "scenario_id": "blind-bearing_wear-002",
      "truth": "BEARING_WEAR",
      "window_end_tick": 49
    },
    {
      "scenario_id": "blind-bearing_wear-002",
      "truth": "BEARING_WEAR",
      "window_end_tick": 54
    },
    {
      "scenario_id": "blind-bearing_wear-002",
      "truth": "BEARING_WEAR",
      "window_end_tick": 59
    }
  ],
  "false_positive_count": 43,
  "false_positive_examples": [
    {
      "scenario_id": "blind-bearing_wear-002",
      "truth": "NORMAL",
      "window_end_tick": 144
    },
    {
      "scenario_id": "blind-bearing_wear-002",
      "truth": "NORMAL",
      "window_end_tick": 149
    },
    {
      "scenario_id": "blind-bearing_wear-002",
      "truth": "NORMAL",
      "window_end_tick": 154
    },
    {
      "scenario_id": "blind-bearing_wear-003",
      "truth": "NORMAL",
      "window_end_tick": 134
    },
    {
      "scenario_id": "blind-bearing_wear-004",
      "truth": "NORMAL",
      "window_end_tick": 159
    },
    {
      "scenario_id": "blind-bearing_wear-004",
      "truth": "NORMAL",
      "window_end_tick": 164
    },
    {
      "scenario_id": "blind-bearing_wear-004",
      "truth": "NORMAL",
      "window_end_tick": 169
    },
    {
      "scenario_id": "blind-bearing_wear-006",
      "truth": "NORMAL",
      "window_end_tick": 149
    },
    {
      "scenario_id": "blind-bearing_wear-007",
      "truth": "NORMAL",
      "window_end_tick": 164
    },
    {
      "scenario_id": "blind-bearing_wear-008",
      "truth": "NORMAL",
      "window_end_tick": 159
    },
    {
      "scenario_id": "blind-bearing_wear-013",
      "truth": "NORMAL",
      "window_end_tick": 164
    },
    {
      "scenario_id": "blind-bearing_wear-013",
      "truth": "NORMAL",
      "window_end_tick": 169
    }
  ],
  "fault_confusion_count": 146,
  "fault_confusion_pairs": {
    "BEARING_WEAR -> OVERLOAD": 35,
    "MISALIGNMENT -> OVERLOAD": 45,
    "MISALIGNMENT -> SENSOR_FAILURE": 3,
    "OVERHEATING -> OVERLOAD": 17,
    "OVERLOAD -> SENSOR_FAILURE": 5,
    "SENSOR_FAILURE -> OVERLOAD": 41
  },
  "low_severity_examples": [
    {
      "scenario_id": "blind-bearing_wear-000",
      "truth": "BEARING_WEAR",
      "window_end_tick": 44
    },
    {
      "scenario_id": "blind-bearing_wear-000",
      "truth": "BEARING_WEAR",
      "window_end_tick": 49
    },
    {
      "scenario_id": "blind-bearing_wear-000",
      "truth": "BEARING_WEAR",
      "window_end_tick": 54
    },
    {
      "scenario_id": "blind-bearing_wear-000",
      "truth": "BEARING_WEAR",
      "window_end_tick": 59
    },
    {
      "scenario_id": "blind-bearing_wear-001",
      "truth": "BEARING_WEAR",
      "window_end_tick": 69
    },
    {
      "scenario_id": "blind-bearing_wear-001",
      "truth": "BEARING_WEAR",
      "window_end_tick": 74
    },
    {
      "scenario_id": "blind-bearing_wear-001",
      "truth": "BEARING_WEAR",
      "window_end_tick": 79
    },
    {
      "scenario_id": "blind-bearing_wear-001",
      "truth": "BEARING_WEAR",
      "window_end_tick": 84
    },
    {
      "scenario_id": "blind-bearing_wear-001",
      "truth": "BEARING_WEAR",
      "window_end_tick": 169
    },
    {
      "scenario_id": "blind-bearing_wear-005",
      "truth": "BEARING_WEAR",
      "window_end_tick": 44
    },
    {
      "scenario_id": "blind-bearing_wear-005",
      "truth": "BEARING_WEAR",
      "window_end_tick": 49
    },
    {
      "scenario_id": "blind-bearing_wear-005",
      "truth": "BEARING_WEAR",
      "window_end_tick": 54
    }
  ],
  "low_severity_false_negative_count": 403,
  "recovery_examples": [
    {
      "scenario_id": "blind-bearing_wear-002",
      "truth": "NORMAL",
      "window_end_tick": 144
    },
    {
      "scenario_id": "blind-bearing_wear-002",
      "truth": "NORMAL",
      "window_end_tick": 149
    },
    {
      "scenario_id": "blind-bearing_wear-002",
      "truth": "NORMAL",
      "window_end_tick": 154
    },
    {
      "scenario_id": "blind-bearing_wear-003",
      "truth": "NORMAL",
      "window_end_tick": 134
    },
    {
      "scenario_id": "blind-bearing_wear-004",
      "truth": "NORMAL",
      "window_end_tick": 159
    },
    {
      "scenario_id": "blind-bearing_wear-004",
      "truth": "NORMAL",
      "window_end_tick": 164
    },
    {
      "scenario_id": "blind-bearing_wear-004",
      "truth": "NORMAL",
      "window_end_tick": 169
    },
    {
      "scenario_id": "blind-bearing_wear-006",
      "truth": "NORMAL",
      "window_end_tick": 149
    },
    {
      "scenario_id": "blind-bearing_wear-007",
      "truth": "NORMAL",
      "window_end_tick": 164
    },
    {
      "scenario_id": "blind-bearing_wear-008",
      "truth": "NORMAL",
      "window_end_tick": 159
    },
    {
      "scenario_id": "blind-bearing_wear-013",
      "truth": "NORMAL",
      "window_end_tick": 164
    },
    {
      "scenario_id": "blind-bearing_wear-013",
      "truth": "NORMAL",
      "window_end_tick": 169
    }
  ],
  "recovery_false_positive_count": 43,
  "sensor_failure_confusion_count": 41,
  "sensor_failure_examples": [
    {
      "scenario_id": "blind-sensor_failure-000",
      "truth": "SENSOR_FAILURE",
      "window_end_tick": 49
    },
    {
      "scenario_id": "blind-sensor_failure-000",
      "truth": "SENSOR_FAILURE",
      "window_end_tick": 54
    },
    {
      "scenario_id": "blind-sensor_failure-000",
      "truth": "SENSOR_FAILURE",
      "window_end_tick": 59
    },
    {
      "scenario_id": "blind-sensor_failure-000",
      "truth": "SENSOR_FAILURE",
      "window_end_tick": 64
    },
    {
      "scenario_id": "blind-sensor_failure-000",
      "truth": "SENSOR_FAILURE",
      "window_end_tick": 69
    },
    {
      "scenario_id": "blind-sensor_failure-000",
      "truth": "SENSOR_FAILURE",
      "window_end_tick": 74
    },
    {
      "scenario_id": "blind-sensor_failure-001",
      "truth": "SENSOR_FAILURE",
      "window_end_tick": 54
    },
    {
      "scenario_id": "blind-sensor_failure-001",
      "truth": "SENSOR_FAILURE",
      "window_end_tick": 59
    },
    {
      "scenario_id": "blind-sensor_failure-001",
      "truth": "SENSOR_FAILURE",
      "window_end_tick": 64
    },
    {
      "scenario_id": "blind-sensor_failure-001",
      "truth": "SENSOR_FAILURE",
      "window_end_tick": 69
    },
    {
      "scenario_id": "blind-sensor_failure-001",
      "truth": "SENSOR_FAILURE",
      "window_end_tick": 74
    },
    {
      "scenario_id": "blind-sensor_failure-001",
      "truth": "SENSOR_FAILURE",
      "window_end_tick": 79
    }
  ]
}
```
