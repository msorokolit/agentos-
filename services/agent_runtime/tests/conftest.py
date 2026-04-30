"""Test fixtures for agent-runtime."""

from __future__ import annotations

from uuid import uuid4

import pytest
from agenticos_shared import db as shared_db
from agenticos_shared.models import Agent, Base, Session, Tenant, Workspace
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db_engine():
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
def _bind_db(db_engine, monkeypatch):
    sm = sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr(shared_db, "_engine", db_engine, raising=False)
    monkeypatch.setattr(shared_db, "_SessionLocal", sm, raising=False)


@pytest.fixture
def db(db_engine):
    sm = sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)
    s = sm()
    try:
        yield s
        s.commit()
    finally:
        s.close()


@pytest.fixture
def workspace(db):
    t = Tenant(id=uuid4(), slug="acme", name="Acme")
    db.add(t)
    w = Workspace(id=uuid4(), tenant_id=t.id, slug="default", name="Default")
    db.add(w)
    db.commit()
    return w


@pytest.fixture
def make_agent(db):
    def _f(workspace_id, **kw):
        a = Agent(
            id=uuid4(),
            workspace_id=workspace_id,
            slug=kw.get("slug", "alpha"),
            name=kw.get("name", "Alpha"),
            system_prompt=kw.get("system_prompt", ""),
            model_alias=kw.get("model_alias", "chat-default"),
            graph_kind="react",
            config=kw.get("config", {}),
            tool_ids=kw.get("tool_ids", []),
            rag_collection_id=kw.get("rag_collection_id"),
        )
        db.add(a)
        db.commit()
        return a

    return _f


@pytest.fixture
def make_session(db):
    def _f(workspace_id, agent_id, user_id=None, title=None):
        s = Session(
            id=uuid4(),
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            title=title,
            meta={},
        )
        db.add(s)
        db.commit()
        return s

    return _f


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("AGENTICOS_ENV", "test")
    from importlib import reload

    from agent_runtime import settings as st

    st.get_settings.cache_clear()
    import agent_runtime.main as main_mod

    reload(main_mod)
    return main_mod.app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test stubs for proxies — used by both graph and route tests.
# ---------------------------------------------------------------------------
class StubLLM:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    async def chat(self, payload):
        self.calls.append(payload)
        if not self.responses:
            raise RuntimeError("no more stub responses")
        return self.responses.pop(0)


class StubTools:
    def __init__(self, descriptors=None, invoke_results=None):
        self.descriptors = descriptors or []
        self.invoke_results = invoke_results or []
        self.invoked = []

    async def list_for(self, workspace_id):
        return self.descriptors

    async def invoke(self, *, tool_id, name, workspace_id, args):
        self.invoked.append({"name": name, "args": args})
        if not self.invoke_results:
            return {"ok": True, "result": {"echo": args}}
        return self.invoke_results.pop(0)


class StubKnowledge:
    def __init__(self, hits=None):
        self.hits = hits or []
        self.calls = 0

    async def search(self, **kwargs):
        self.calls += 1
        return {"query": kwargs.get("query"), "hits": self.hits}


@pytest.fixture
def StubLLMCls():
    return StubLLM


@pytest.fixture
def StubToolsCls():
    return StubTools


@pytest.fixture
def StubKnowledgeCls():
    return StubKnowledge
