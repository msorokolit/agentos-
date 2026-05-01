"""Integration test scaffold.

These tests do **not** require docker. They wire up the api-gateway and
each downstream FastAPI app against a single shared in-memory SQLite DB
and route service-to-service HTTP via ``httpx``'s ASGI transport.

External boundaries (LLM, NATS, OPA) are mocked with ``respx`` per test.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from agenticos_shared import db as shared_db
from agenticos_shared.models import Base
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_lock = threading.Lock()


@pytest.fixture
def shared_engine():
    """Use a real Postgres when ``AGENTICOS_PG_TEST_URL`` is set (the CI
    integration job points it at the pgvector service container);
    otherwise fall back to in-memory SQLite for fast local runs."""

    import os

    pg_url = os.environ.get("AGENTICOS_PG_TEST_URL")
    if pg_url:
        engine = create_engine(pg_url, future=True, pool_pre_ping=True)
        # Reset state between tests so each starts on a clean slate.
        # ``alembic upgrade head`` (run once in CI) created the tables.
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.exec_driver_sql(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE')
        yield engine
        engine.dispose()
        return

    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _bind_shared_db(shared_engine, monkeypatch):
    sm = sessionmaker(bind=shared_engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr(shared_db, "_engine", shared_engine, raising=False)
    monkeypatch.setattr(shared_db, "_SessionLocal", sm, raising=False)


@pytest.fixture
def shared_session(shared_engine):
    sm = sessionmaker(bind=shared_engine, autoflush=False, autocommit=False, future=True)
    s = sm()
    try:
        yield s
        s.commit()
    finally:
        s.close()


@pytest.fixture
def api_app(monkeypatch):
    monkeypatch.setenv("AGENTICOS_ENV", "test")
    monkeypatch.setenv("AGENTICOS_SECRET_KEY", "test-secret-32-bytes-or-more!!!")
    from importlib import reload

    from api_gateway import settings as st

    st.get_settings.cache_clear()
    # Drop the model-capability cache so a previous test's mock data
    # doesn't leak into this one.
    from api_gateway import model_capabilities as mc

    mc._clear_cache()
    import api_gateway.main as main_mod

    reload(main_mod)
    return main_mod.app


@pytest.fixture
def llm_app(monkeypatch):
    from importlib import reload

    from llm_gateway import settings as st

    st.get_settings.cache_clear()
    import llm_gateway.main as main_mod

    reload(main_mod)
    return main_mod.app


@pytest.fixture
def tools_app(monkeypatch):
    from importlib import reload

    from tool_registry import settings as st

    st.get_settings.cache_clear()
    import tool_registry.main as main_mod

    reload(main_mod)
    return main_mod.app


@pytest.fixture
def knowledge_app(monkeypatch):
    from importlib import reload

    from knowledge_svc import settings as st

    st.get_settings.cache_clear()
    import knowledge_svc.main as main_mod

    reload(main_mod)
    return main_mod.app


@pytest.fixture
def memory_app(monkeypatch):
    from importlib import reload

    from memory_svc import settings as st

    st.get_settings.cache_clear()
    import memory_svc.main as main_mod

    reload(main_mod)
    return main_mod.app


@pytest.fixture
def runtime_app(monkeypatch):
    from importlib import reload

    from agent_runtime import settings as st

    st.get_settings.cache_clear()
    import agent_runtime.main as main_mod

    reload(main_mod)
    return main_mod.app


class _RouterTransport(httpx.AsyncBaseTransport):
    """ASGI for known hosts, real HTTPTransport (respx-mockable) for the rest."""

    def __init__(self, host_to_app: dict[str, Any]) -> None:
        self._host_to_app = host_to_app
        self._cache: dict[str, httpx.AsyncBaseTransport] = {}
        self._fallback: httpx.AsyncBaseTransport | None = None

    def _t_for(self, host: str) -> httpx.AsyncBaseTransport:
        if host in self._host_to_app:
            if host not in self._cache:
                self._cache[host] = httpx.ASGITransport(app=self._host_to_app[host])
            return self._cache[host]
        if self._fallback is None:
            self._fallback = httpx.AsyncHTTPTransport()
        return self._fallback

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._t_for(request.url.host).handle_async_request(request)

    async def aclose(self) -> None:
        for t in list(self._cache.values()):
            await t.aclose()
        self._cache.clear()
        if self._fallback is not None:
            await self._fallback.aclose()


# Bind the real ``httpx.AsyncClient`` once so our factory can call it
# without the recursive monkeypatch trampoline.
_REAL_ASYNC_CLIENT = httpx.AsyncClient


class StackRouter:
    """Routes outbound httpx requests from the api-gateway to in-process apps."""

    def __init__(self, host_to_app: dict[str, Any]) -> None:
        self.host_to_app = host_to_app

    def make_client(self, *args, **kwargs) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        kwargs.setdefault("timeout", 30.0)
        kwargs.setdefault("base_url", "")
        return _REAL_ASYNC_CLIENT(transport=_RouterTransport(self.host_to_app), **kwargs)


@pytest.fixture
def install_stack_router(
    monkeypatch,
    api_app,
    llm_app,
    tools_app,
    knowledge_app,
    memory_app,
    runtime_app,
) -> Iterator[StackRouter]:
    """Patch the api-gateway's outbound httpx so requests stay in-process."""

    router = StackRouter(
        {
            "llm-gateway": llm_app,
            "tool-registry": tools_app,
            "knowledge-svc": knowledge_app,
            "memory-svc": memory_app,
            "agent-runtime": runtime_app,
        }
    )

    # Patch httpx.AsyncClient at the module-global level — every service we
    # care about accesses it as ``httpx.AsyncClient``.
    monkeypatch.setattr(httpx, "AsyncClient", router.make_client)

    yield router


@pytest.fixture
def api_client(api_app, install_stack_router) -> TestClient:
    return TestClient(api_app)
