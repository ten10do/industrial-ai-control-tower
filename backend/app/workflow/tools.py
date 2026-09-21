"""Read-only Phase 5 tool registry and per-agent allowlists."""

TOOL_REGISTRY = {
    "read_diagnosis": "Read the bound structured diagnosis.",
    "read_evidence": "Read the bound cited knowledge evidence.",
    "read_device_metadata": "Read metadata for the bound device.",
    "read_maintenance_history": "Read maintenance history for the bound device.",
}

AGENT_TOOL_ALLOWLISTS = {
    "triage": frozenset({"read_diagnosis", "read_evidence", "read_device_metadata"}),
    "planning": frozenset(
        {"read_diagnosis", "read_evidence", "read_device_metadata", "read_maintenance_history"}
    ),
    "safety_review": frozenset({"read_diagnosis", "read_evidence", "read_device_metadata"}),
}
