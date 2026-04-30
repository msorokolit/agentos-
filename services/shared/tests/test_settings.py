"""Settings load from env vars and have sane defaults."""

from __future__ import annotations

import os

import pytest

from agenticos_shared.settings import BaseServiceSettings


def test_defaults_load() -> None:
    s = BaseServiceSettings()
    assert s.env in {"development", "staging", "production", "test"}
    assert s.embed_dim > 0
    assert s.database_url.startswith("postgresql")


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTICOS_ENV", "test")
    monkeypatch.setenv("EMBED_DIM", "1024")
    monkeypatch.setenv("REDIS_URL", "redis://example:6379/3")
    s = BaseServiceSettings()
    assert s.env == "test"
    assert s.embed_dim == 1024
    assert s.redis_url == "redis://example:6379/3"
    assert s.is_test is True
