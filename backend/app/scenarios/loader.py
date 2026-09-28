"""Load strict YAML or JSON scenario definitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from app.scenarios.contracts import ScenarioDefinition


def load_scenario(path: Path) -> ScenarioDefinition:
    """Validate one scenario file, rejecting unknown fields and invalid values."""

    if path.suffix.lower() not in {".yaml", ".yml", ".json"}:
        raise ValueError(f"unsupported scenario file: {path}")
    raw = path.read_text(encoding="utf-8")
    data: Any = json.loads(raw) if path.suffix.lower() == ".json" else yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise ValueError(f"scenario must be a mapping: {path}")
    return ScenarioDefinition.model_validate(data)


def load_suite(path: Path) -> list[ScenarioDefinition]:
    """Load a directory in stable filename order and reject duplicate ids."""

    if not path.is_dir():
        raise ValueError(f"scenario suite is not a directory: {path}")
    definitions = [
        load_scenario(item)
        for item in sorted(path.iterdir())
        if item.suffix.lower() in {".yaml", ".yml", ".json"}
    ]
    if not definitions:
        raise ValueError(f"scenario suite is empty: {path}")
    ids = [item.scenario_id for item in definitions]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise ValueError(f"duplicate scenario ids: {duplicates}")
    return definitions
