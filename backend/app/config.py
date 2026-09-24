"""Application configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    log_level: str = "INFO"
    database_url: str = (
        "postgresql+asyncpg://postgres:change-me-in-dotenv@localhost:5432/"
        "industrial_ai_control_tower"
    )
    database_pool_size: int = 5
    database_max_overflow: int = 5
    redis_url: str = "redis://localhost:6379/0"
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_topic: str = "industrial/devices/+/telemetry"
    mqtt_enabled: bool = True
    websocket_queue_size: int = 1
    diagnosis_enabled: bool = True
    diagnosis_artifact_path: Path = Path("artifacts/diagnosis-v1.1.joblib")
    diagnosis_manifest_path: Path = Path("artifacts/model_manifest-v1.1.json")
    knowledge_enabled: bool = True
    knowledge_index_path: Path = Path("knowledge/index-v1.json")
    knowledge_corpus_version: str = "industrial-maintenance-corpus-v1"
    knowledge_embedding_version: str = "local-hash-embedding-v1"
    workflow_enabled: bool = False
    agent_provider: str = "openai_compatible"
    agent_model: str = ""
    agent_api_key: SecretStr | None = None
    agent_base_url: str = "https://api.openai.com/v1"
    agent_temperature: float = 0.1
    agent_timeout_seconds: float = 30.0
    agent_max_attempts: int = 3
    agent_backoff_seconds: float = 0.5
    agent_schema_max_attempts: int = 2
    observability_enabled: bool = True
    gateway_enabled: bool = False
    gateway_config_path: Path = Path("configs/gateway_devices.yaml")
    gateway_failure_threshold: int = 3
    gateway_reconnect_threshold: int = 6
    gateway_max_reconnect_attempts: int = 5
    gateway_backoff_initial_seconds: float = 1.0
    gateway_backoff_max_seconds: float = 30.0
    # Phase 6.8. When enabled, a published database configuration is authoritative
    # and the YAML file only bootstraps devices that have no published version.
    config_management_enabled: bool = False
    gateway_apply_timeout_seconds: float = 10.0
    # Phase 6.12 security foundation. Authentication and authorization are always
    # enforced on the endpoints that declare a permission; only the two knobs
    # below are configurable. The signing secret has no default on purpose: a
    # generated fallback would silently invalidate every token on restart and
    # would make an unconfigured deployment look configured.
    security_jwt_secret: SecretStr | None = None
    security_access_token_ttl_seconds: int = 3600
    security_registration_enabled: bool = True
    security_login_rate_limit_attempts: int = 5
    security_login_rate_limit_window_seconds: int = 60

    @property
    def checkpoint_database_url(self) -> str:
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated configuration."""
    return Settings()
