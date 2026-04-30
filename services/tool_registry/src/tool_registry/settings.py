"""tool-registry-specific settings."""

from __future__ import annotations

from functools import lru_cache

from agenticos_shared.settings import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "tool-registry"


@lru_cache
def get_settings() -> Settings:
    return Settings()
