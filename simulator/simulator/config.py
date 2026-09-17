"""Simulator configuration with default < environment < CLI priority."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class SimulatorConfig(BaseSettings):
    """Configuration loaded from environment variables and CLI overrides."""

    model_config = SettingsConfigDict(
        env_prefix="SIMULATOR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    device_id: str = "MOTOR-001"
    seed: int | None = 42
    sample_interval: float = 1.0
    max_ticks: int | None = None
    realtime: bool = True
    log_level: str = "INFO"

    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    mqtt_topic_prefix: str = "industrial"

    fault_type: str | None = None
    fault_start_tick: int = 30
    fault_duration: int = 60
    fault_severity: float = 1.0
