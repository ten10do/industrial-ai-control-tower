"""Deterministic conversion from diagnosis evidence to retrieval intent."""

from __future__ import annotations

from app.knowledge.contracts import BuiltQuery, KnowledgeFilters, KnowledgeQuery

FAULT_TERMS: dict[str, tuple[str, ...]] = {
    "BEARING_WEAR": (
        "bearing wear",
        "bearing damage",
        "lubrication",
        "vibration",
        "bearing temperature",
    ),
    "OVERLOAD": ("motor overload", "excess current", "load", "overheating", "trip"),
    "OVERHEATING": (
        "motor overheating",
        "temperature rise",
        "ventilation",
        "voltage unbalance",
        "lubrication",
    ),
    "MISALIGNMENT": (
        "shaft misalignment",
        "alignment",
        "vibration",
        "coupling",
        "bearing temperature",
    ),
    "SENSOR_FAILURE": (
        "sensor failure",
        "instrumentation",
        "measurement verification",
        "wiring",
        "calibration",
    ),
}


def build_query(query: KnowledgeQuery) -> BuiltQuery:
    fault_type = query.fault_type.upper()
    terms = list(FAULT_TERMS.get(fault_type, ()))
    symptoms = [item.strip().lower() for item in query.symptoms if item.strip()]
    terms.extend(symptoms)
    exact = [fault_type.replace("_", " ").lower()]
    if query.device_model:
        exact.append(query.device_model.lower())
    semantic_parts = [query.device_type.replace("_", " "), query.objective, *terms]
    return BuiltQuery(
        search_terms=list(dict.fromkeys(terms)),
        exact_terms=exact,
        semantic_query=" ".join(semantic_parts),
        filters=KnowledgeFilters(
            equipment_type=query.device_type,
            model=query.device_model,
        ),
        supported_fault=fault_type in FAULT_TERMS,
    )


def build_free_text(query: str, filters: KnowledgeFilters) -> BuiltQuery:
    terms = list(dict.fromkeys(part.lower() for part in query.split() if len(part) > 2))
    return BuiltQuery(
        search_terms=terms,
        exact_terms=[],
        semantic_query=query,
        filters=filters,
        supported_fault=True,
    )
