"""api-gateway-specific settings."""

from __future__ import annotations

from functools import lru_cache

from agenticos_shared.settings import BaseServiceSettings
from pydantic import Field


class Settings(BaseServiceSettings):
    service_name: str = "api-gateway"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    api_prefix: str = "/api/v1"
    rate_limit_per_minute: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
