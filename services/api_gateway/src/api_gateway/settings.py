"""api-gateway-specific settings."""

from __future__ import annotations

from functools import lru_cache

from agenticos_shared.settings import BaseServiceSettings
from pydantic import Field


class Settings(BaseServiceSettings):
    service_name: str = "api-gateway"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    api_prefix: str = "/api/v1"
    rate_limit_per_minute: int = 600

    # Web UI redirect target after successful OIDC callback.
    web_ui_url: str = Field(default="http://localhost:3000", alias="WEB_UI_URL")
    # Cookie used to keep the browser session.
    session_cookie_name: str = Field(default="agos_session", alias="SESSION_COOKIE_NAME")
    session_ttl_seconds: int = Field(default=12 * 3600, alias="SESSION_TTL_SECONDS")
    session_cookie_secure: bool = Field(default=False, alias="SESSION_COOKIE_SECURE")
    # Default tenant slug that a newly-seen OIDC user is auto-provisioned into.
    auto_provision_tenant: str = Field(default="acme", alias="AUTO_PROVISION_TENANT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
