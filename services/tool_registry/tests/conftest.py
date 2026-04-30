"""Shared fixtures for tool-registry tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from agenticos_shared import db as shared_db
from agenticos_shared.models import Base, Tenant, Workspace
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
def app(monkeypatch):
    monkeypatch.setenv("AGENTICOS_ENV", "test")
    from importlib import reload

    from tool_registry import settings as st

    st.get_settings.cache_clear()
    import tool_registry.main as main_mod

    reload(main_mod)
    return main_mod.app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)
