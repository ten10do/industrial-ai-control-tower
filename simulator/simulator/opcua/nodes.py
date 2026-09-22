"""Deterministic node definitions for the OPC UA server simulator."""

NAMESPACE_URI = "urn:industrial-ai-control-tower:simulator"
DEVICE_ID = "MOTOR-001"

NODE_BROWSE_NAMES: dict[str, str] = {
    "temperature": "Temperature",
    "vibration": "Vibration",
    "current": "Current",
    "rpm": "RPM",
    "load": "Load",
}

DETERMINISTIC_VALUES: dict[str, float | int] = {
    "temperature": 68.2,
    "vibration": 7.1,
    "current": 12.4,
    "rpm": 1480,
    "load": 72.0,
}


def node_identifier(signal: str, device_id: str = DEVICE_ID) -> str:
    """Return the stable string identifier for a configured signal."""

    return f"{device_id}/{NODE_BROWSE_NAMES[signal]}"
