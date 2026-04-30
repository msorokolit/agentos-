"""Common settings for all AgenticOS services.

Each service typically subclasses :class:`BaseServiceSettings` to add
service-specific fields. All fields can be overridden via environment
variables (case-insensitive).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Env = Literal["development", "staging", "production", "test"]


class BaseServiceSettings(BaseSettings):
    """Settings shared by every service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Identity / runtime ---
    service_name: str = Field(default="agenticos-service")
    env: Env = Field(default="development", alias="AGENTICOS_ENV")
    log_level: str = Field(default="INFO", alias="AGENTICOS_LOG_LEVEL")
    secret_key: str = Field(
        default="dev-only-secret-change-me-please-32bytes!",
        alias="AGENTICOS_SECRET_KEY",
    )

    # --- Datastores ---
    database_url: str = Field(
        default="postgresql+psycopg://agenticos:agenticos@localhost:5432/agenticos",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    nats_url: str = Field(default="nats://localhost:4222", alias="NATS_URL")

    # --- Object storage ---
    s3_endpoint: str = Field(default="http://localhost:9000", alias="S3_ENDPOINT")
    s3_access_key: str = Field(default="agenticos", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="agenticos-minio", alias="S3_SECRET_KEY")
    s3_bucket: str = Field(default="agenticos", alias="S3_BUCKET")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")

    # --- AuthN ---
    oidc_issuer: str = Field(
        default="http://localhost:8080/realms/agenticos", alias="OIDC_ISSUER"
    )
    oidc_client_id: str = Field(default="agenticos-web", alias="OIDC_CLIENT_ID")
    oidc_client_secret: str = Field(default="dev-client-secret", alias="OIDC_CLIENT_SECRET")
    oidc_redirect_uri: str = Field(
        default="http://localhost:8080/api/v1/auth/oidc/callback",
        alias="OIDC_REDIRECT_URI",
    )

    # --- LLM ---
    ollama_url: str = Field(default="http://localhost:11434", alias="OLLAMA_URL")
    default_chat_model_alias: str = Field(
        default="chat-default", alias="DEFAULT_CHAT_MODEL_ALIAS"
    )
    default_embed_model_alias: str = Field(
        default="embed-default", alias="DEFAULT_EMBED_MODEL_ALIAS"
    )
    embed_dim: int = Field(default=768, alias="EMBED_DIM")

    # --- Policy / OPA ---
    opa_url: str = Field(default="http://localhost:8181", alias="OPA_URL")

    # --- Observability ---
    otel_endpoint: str | None = Field(
        default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_service_namespace: str = Field(
        default="agenticos", alias="OTEL_SERVICE_NAMESPACE"
    )

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def is_test(self) -> bool:
        return self.env == "test"


@lru_cache
def get_settings() -> BaseServiceSettings:
    """Return a process-wide singleton instance.

    Subclasses should provide their own ``get_settings`` or call
    ``MyServiceSettings()`` directly; this helper is convenient for
    code that only needs the shared fields.
    """

    return BaseServiceSettings()
