# Synthetic Classification Separability Audit

## Leakage checks

- Feature count: 76
- Runtime schema match: True
- Forbidden direct fields present: `[]`
- Scenario/seed overlap: `{"train_test": {"scenarios": 0, "seeds": 0}, "train_validation": {"scenarios": 0, "seeds": 0}, "validation_test": {"scenarios": 0, "seeds": 0}}`
- Metadata such as scenario ID and seed remains in evaluation arrays only; it is not in `X`.

## Why Macro F1 reached 1.0000

The split is leakage-safe, but all splits come from one simulator family. Fault effects are
deliberately class-specific: bearing wear adds strong vibration plus bearing heat; overload adds
load/current/power and RPM droop; overheating adds motor/bearing heat with little vibration;
misalignment primarily adds vibration with a small current/thermal effect; sensor failure creates
stuck/intermittent temperature behavior. Severity changes magnitude but not this causal template.

Even a nearest-training-centroid classifier over standardized features reaches
0.9052 accuracy on exposed Test V1 fault windows.
This supports synthetic separability as the explanation; it does not support a real-world 100%
claim.

Train, validation, and test use different scenarios and seeds but draw load, severity, timing, and
duration from the same ranges. Configuration summaries are retained below for audit.

```json
{
  "test": {
    "BEARING_WEAR": {
      "count": 7,
      "duration": {
        "max": 74.0,
        "mean": 66.71428571428571,
        "min": 56.0
      },
      "initial_load_pct": {
        "max": 71.495,
        "mean": 49.17642857142857,
        "min": 36.71
      },
      "severity": {
        "max": 0.9931,
        "mean": 0.7903714285714285,
        "min": 0.5574
      },
      "start_tick": {
        "max": 55.0,
        "mean": 41.857142857142854,
        "min": 36.0
      }
    },
    "MISALIGNMENT": {
      "count": 7,
      "duration": {
        "max": 69.0,
        "mean": 61.57142857142857,
        "min": 57.0
      },
      "initial_load_pct": {
        "max": 63.829,
        "mean": 55.07271428571429,
        "min": 38.717
      },
      "severity": {
        "max": 0.9707,
        "mean": 0.8037285714285715,
        "min": 0.6417
      },
      "start_tick": {
        "max": 53.0,
        "mean": 46.142857142857146,
        "min": 37.0
      }
    },
    "NORMAL": {
      "count": 8,
      "duration": {
        "max": 0.0,
        "mean": 0.0,
        "min": 0.0
      },
      "initial_load_pct": {
        "max": 74.427,
        "mean": 57.116875,
        "min": 36.446
      },
      "severity": {
        "max": 0.0,
        "mean": 0.0,
        "min": 0.0
      },
      "start_tick": {
        "max": -1.0,
        "mean": -1.0,
        "min": -1.0
      }
    },
    "OVERHEATING": {
      "count": 7,
      "duration": {
        "max": 66.0,
        "mean": 61.857142857142854,
        "min": 57.0
      },
      "initial_load_pct": {
        "max": 73.105,
        "mean": 55.694142857142865,
        "min": 42.04
      },
      "severity": {
        "max": 0.9728,
        "mean": 0.7704000000000001,
        "min": 0.6266
      },
      "start_tick": {
        "max": 55.0,
        "mean": 43.0,
        "min": 35.0
      }
    },
    "OVERLOAD": {
      "count": 7,
      "duration": {
        "max": 73.0,
        "mean": 67.0,
        "min": 61.0
      },
      "initial_load_pct": {
        "max": 69.83,
        "mean": 52.12885714285714,
        "min": 41.412
      },
      "severity": {
        "max": 0.9651,
        "mean": 0.8209714285714285,
        "min": 0.7056
      },
      "start_tick": {
        "max": 55.0,
        "mean": 41.857142857142854,
        "min": 36.0
      }
    },
    "SENSOR_FAILURE": {
      "count": 7,
      "duration": {
        "max": 75.0,
        "mean": 67.14285714285714,
        "min": 60.0
      },
      "initial_load_pct": {
        "max": 73.03,
        "mean": 53.193285714285715,
        "min": 36.393
      },
      "severity": {
        "max": 0.985,
        "mean": 0.8897571428571428,
        "min": 0.7025
      },
      "start_tick": {
        "max": 52.0,
        "mean": 44.57142857142857,
        "min": 36.0
      }
    }
  },
  "train": {
    "BEARING_WEAR": {
      "count": 19,
      "duration": {
        "max": 74.0,
        "mean": 65.3157894736842,
        "min": 56.0
      },
      "initial_load_pct": {
        "max": 74.601,
        "mean": 57.30226315789472,
        "min": 35.358
      },
      "severity": {
        "max": 0.9956,
        "mean": 0.7819473684210527,
        "min": 0.5546
      },
      "start_tick": {
        "max": 55.0,
        "mean": 45.578947368421055,
        "min": 35.0
      }
    },
    "MISALIGNMENT": {
      "count": 19,
      "duration": {
        "max": 74.0,
        "mean": 65.84210526315789,
        "min": 57.0
      },
      "initial_load_pct": {
        "max": 72.403,
        "mean": 53.853157894736846,
        "min": 36.638
      },
      "severity": {
        "max": 0.9836,
        "mean": 0.8362526315789475,
        "min": 0.6007
      },
      "start_tick": {
        "max": 55.0,
        "mean": 43.94736842105263,
        "min": 35.0
      }
    },
    "NORMAL": {
      "count": 24,
      "duration": {
        "max": 0.0,
        "mean": 0.0,
        "min": 0.0
      },
      "initial_load_pct": {
        "max": 73.997,
        "mean": 58.928041666666665,
        "min": 35.512
      },
      "severity": {
        "max": 0.0,
        "mean": 0.0,
        "min": 0.0
      },
      "start_tick": {
        "max": -1.0,
        "mean": -1.0,
        "min": -1.0
      }
    },
    "OVERHEATING": {
      "count": 19,
      "duration": {
        "max": 73.0,
        "mean": 65.6842105263158,
        "min": 57.0
      },
      "initial_load_pct": {
        "max": 73.048,
        "mean": 56.34863157894738,
        "min": 35.921
      },
      "severity": {
        "max": 0.9471,
        "mean": 0.7165684210526316,
        "min": 0.5503
      },
      "start_tick": {
        "max": 55.0,
        "mean": 46.526315789473685,
        "min": 36.0
      }
    },
    "OVERLOAD": {
      "count": 19,
      "duration": {
        "max": 73.0,
        "mean": 61.10526315789474,
        "min": 55.0
      },
      "initial_load_pct": {
        "max": 74.354,
        "mean": 55.51484210526316,
        "min": 35.219
      },
      "severity": {
        "max": 0.9762,
        "mean": 0.7619473684210526,
        "min": 0.5577
      },
      "start_tick": {
        "max": 54.0,
        "mean": 44.89473684210526,
        "min": 35.0
      }
    },
    "SENSOR_FAILURE": {
      "count": 19,
      "duration": {
        "max": 75.0,
        "mean": 64.89473684210526,
        "min": 55.0
      },
      "initial_load_pct": {
        "max": 73.365,
        "mean": 54.59763157894737,
        "min": 35.198
      },
      "severity": {
        "max": 0.9864,
        "mean": 0.7609736842105264,
        "min": 0.6155
      },
      "start_tick": {
        "max": 55.0,
        "mean": 44.36842105263158,
        "min": 35.0
      }
    }
  },
  "validation": {
    "BEARING_WEAR": {
      "count": 6,
      "duration": {
        "max": 72.0,
        "mean": 66.83333333333333,
        "min": 59.0
      },
      "initial_load_pct": {
        "max": 57.275,
        "mean": 46.99316666666667,
        "min": 36.513
      },
      "severity": {
        "max": 0.8715,
        "mean": 0.8152499999999999,
        "min": 0.6742
      },
      "start_tick": {
        "max": 53.0,
        "mean": 50.0,
        "min": 42.0
      }
    },
    "MISALIGNMENT": {
      "count": 6,
      "duration": {
        "max": 73.0,
        "mean": 61.5,
        "min": 58.0
      },
      "initial_load_pct": {
        "max": 65.642,
        "mean": 53.094,
        "min": 42.651
      },
      "severity": {
        "max": 0.9517,
        "mean": 0.8945333333333334,
        "min": 0.8242
      },
      "start_tick": {
        "max": 52.0,
        "mean": 44.333333333333336,
        "min": 37.0
      }
    },
    "NORMAL": {
      "count": 8,
      "duration": {
        "max": 0.0,
        "mean": 0.0,
        "min": 0.0
      },
      "initial_load_pct": {
        "max": 71.932,
        "mean": 55.5,
        "min": 41.786
      },
      "severity": {
        "max": 0.0,
        "mean": 0.0,
        "min": 0.0
      },
      "start_tick": {
        "max": -1.0,
        "mean": -1.0,
        "min": -1.0
      }
    },
    "OVERHEATING": {
      "count": 6,
      "duration": {
        "max": 71.0,
        "mean": 62.666666666666664,
        "min": 55.0
      },
      "initial_load_pct": {
        "max": 73.834,
        "mean": 64.20583333333333,
        "min": 57.628
      },
      "severity": {
        "max": 0.9323,
        "mean": 0.8332833333333333,
        "min": 0.6971
      },
      "start_tick": {
        "max": 55.0,
        "mean": 45.5,
        "min": 36.0
      }
    },
    "OVERLOAD": {
      "count": 6,
      "duration": {
        "max": 74.0,
        "mean": 63.166666666666664,
        "min": 55.0
      },
      "initial_load_pct": {
        "max": 73.165,
        "mean": 53.89416666666667,
        "min": 39.141
      },
      "severity": {
        "max": 0.9303,
        "mean": 0.7077,
        "min": 0.6058
      },
      "start_tick": {
        "max": 54.0,
        "mean": 47.0,
        "min": 38.0
      }
    },
    "SENSOR_FAILURE": {
      "count": 6,
      "duration": {
        "max": 75.0,
        "mean": 71.0,
        "min": 62.0
      },
      "initial_load_pct": {
        "max": 72.732,
        "mean": 55.080833333333324,
        "min": 36.383
      },
      "severity": {
        "max": 0.9944,
        "mean": 0.7400166666666667,
        "min": 0.5762
      },
      "start_tick": {
        "max": 50.0,
        "mean": 44.0,
        "min": 36.0
      }
    }
  }
}
```

## Strongest class-template features

### BEARING_WEAR

```json
[
  {
    "feature": "bearing_motor_delta__mean",
    "standardized_effect": 1.9738250991044841
  },
  {
    "feature": "vibration_mm_s__max",
    "standardized_effect": 1.488842086989993
  },
  {
    "feature": "vibration_mm_s__mean",
    "standardized_effect": 1.3684581263939444
  },
  {
    "feature": "vibration_mm_s__median",
    "standardized_effect": 1.341814971462005
  },
  {
    "feature": "bearing_temperature_c__mean",
    "standardized_effect": 1.27385750254114
  },
  {
    "feature": "bearing_temperature_c__median",
    "standardized_effect": 1.267854395904079
  },
  {
    "feature": "bearing_temperature_c__min",
    "standardized_effect": 1.2306127543325978
  },
  {
    "feature": "bearing_temperature_c__max",
    "standardized_effect": 1.2260432934407992
  }
]
```

### OVERLOAD

```json
[
  {
    "feature": "power_kw__max",
    "standardized_effect": 2.260215407254765
  },
  {
    "feature": "current_a__max",
    "standardized_effect": 2.259860396049902
  },
  {
    "feature": "load_pct__max",
    "standardized_effect": 2.2140181679560764
  },
  {
    "feature": "rpm__min",
    "standardized_effect": 2.166864636929143
  },
  {
    "feature": "current_a__mean",
    "standardized_effect": 2.100503504427156
  },
  {
    "feature": "power_kw__mean",
    "standardized_effect": 2.100302800652514
  },
  {
    "feature": "current_a__median",
    "standardized_effect": 2.0577533835559665
  },
  {
    "feature": "load_pct__mean",
    "standardized_effect": 2.0575308958850598
  }
]
```

### OVERHEATING

```json
[
  {
    "feature": "temperature_c__variance",
    "standardized_effect": 2.546852493244192
  },
  {
    "feature": "bearing_temperature_c__variance",
    "standardized_effect": 2.4347749280420468
  },
  {
    "feature": "temperature_c__std",
    "standardized_effect": 2.3245654829576203
  },
  {
    "feature": "temperature_c__range",
    "standardized_effect": 2.321383413039914
  },
  {
    "feature": "temperature_c__delta",
    "standardized_effect": 2.2874492270263818
  },
  {
    "feature": "temperature_c__slope",
    "standardized_effect": 2.2216107913842986
  },
  {
    "feature": "bearing_temperature_c__std",
    "standardized_effect": 2.085138516732692
  },
  {
    "feature": "bearing_temperature_c__range",
    "standardized_effect": 2.079401770863388
  }
]
```

### MISALIGNMENT

```json
[
  {
    "feature": "vibration_mm_s__max",
    "standardized_effect": 0.9769246736141292
  },
  {
    "feature": "vibration_mm_s__mean",
    "standardized_effect": 0.896299359493326
  },
  {
    "feature": "vibration_mm_s__median",
    "standardized_effect": 0.8802611863450163
  },
  {
    "feature": "power_per_load__mean",
    "standardized_effect": 0.7749654248401144
  },
  {
    "feature": "current_per_load__mean",
    "standardized_effect": 0.7743746660970369
  },
  {
    "feature": "vibration_mm_s__min",
    "standardized_effect": 0.7693436780193758
  },
  {
    "feature": "bearing_temperature_c__max",
    "standardized_effect": 0.7106976503003878
  },
  {
    "feature": "load_pct__max",
    "standardized_effect": 0.7097245394025806
  }
]
```

### SENSOR_FAILURE

```json
[
  {
    "feature": "bearing_temperature_c__max",
    "standardized_effect": 1.2638501956381292
  },
  {
    "feature": "vibration_mm_s__max",
    "standardized_effect": 1.2024709853318247
  },
  {
    "feature": "bearing_temperature_c__mean",
    "standardized_effect": 1.1056583323204099
  },
  {
    "feature": "vibration_mm_s__mean",
    "standardized_effect": 1.10163459061733
  },
  {
    "feature": "vibration_mm_s__median",
    "standardized_effect": 1.080269915390985
  },
  {
    "feature": "bearing_temperature_c__median",
    "standardized_effect": 1.0758752738328305
  },
  {
    "feature": "temperature_c__median",
    "standardized_effect": 1.0655700746991976
  },
  {
    "feature": "temperature_c__mean",
    "standardized_effect": 1.0625640879447182
  }
]
```

## Conclusion

No direct label or group leakage was found. Perfect Random Forest classification is credible inside this synthetic benchmark because each fault injects a stable, class-specific signal signature under the same generation family. It is not evidence of perfect real-world fault diagnosis.
