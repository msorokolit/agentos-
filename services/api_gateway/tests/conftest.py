"""Shared test fixtures for api-gateway.

Strategy
--------
We override the production DB engine with an in-memory SQLite DB,
create all tables from the SQLAlchemy metadata, then build a
`TestClient` against the wired app. Audit emission is left as a no-op
emitter (no NATS) — it logs but does not write to DB unless we want it to.

OIDC is mocked end-to-end with `respx` in the OIDC tests.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from agenticos_shared import db as shared_db
from agenticos_shared.models import (
    AuditEventRow,
    Base,
    Tenant,
    User,
    Workspace,
    WorkspaceMember,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def db_engine():
    # StaticPool + check_same_thread=False so the in-memory DB is shared
    # across threads (TestClient runs the app in a worker thread).
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


@pytest.fixture
def db_sessionmaker(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture(autouse=True)
def _bind_shared_db(db_engine, db_sessionmaker, monkeypatch):
    """Point ``agenticos_shared.db`` at the in-memory SQLite engine."""

    monkeypatch.setattr(shared_db, "_engine", db_engine, raising=False)
    monkeypatch.setattr(shared_db, "_SessionLocal", db_sessionmaker, raising=False)
    yield


@pytest.fixture
def db(db_sessionmaker) -> Iterator[Session]:
    s = db_sessionmaker()
    try:
        yield s
        s.commit()
    finally:
        s.close()


@pytest.fixture
def settings(monkeypatch):
    """Tweak settings for tests + clear the lru_cache."""

    monkeypatch.setenv("AGENTICOS_SECRET_KEY", "test-secret-32-bytes-or-more!!!")
    monkeypatch.setenv("AGENTICOS_ENV", "test")
    from api_gateway.settings import get_settings

    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def app(settings):
    """Build the FastAPI app — re-imported each test to pick up cleared caches."""

    from importlib import reload

    import api_gateway.main as gw_main

    reload(gw_main)
    return gw_main.app


@pytest.fixture
def client(app) -> TestClient:
    # Skip lifespan startup (would try to connect to NATS) — not needed for tests.
    c = TestClient(app)
    return c


# ---------------------------------------------------------------------------
# Domain factories
# ---------------------------------------------------------------------------
@pytest.fixture
def make_tenant(db):
    def _f(slug: str = "acme", name: str | None = None) -> Tenant:
        t = Tenant(id=uuid4(), slug=slug, name=name or slug.title())
        db.add(t)
        db.commit()
        return t

    return _f


@pytest.fixture
def make_user(db):
    def _f(
        tenant_id: UUID,
        email: str = "alice@example.com",
        display_name: str = "Alice",
        is_superuser: bool = False,
    ) -> User:
        u = User(
            id=uuid4(),
            tenant_id=tenant_id,
            email=email,
            display_name=display_name,
            is_superuser=is_superuser,
        )
        db.add(u)
        db.commit()
        return u

    return _f


@pytest.fixture
def make_workspace(db):
    def _f(tenant_id: UUID, slug: str = "default", name: str | None = None) -> Workspace:
        w = Workspace(
            id=uuid4(),
            tenant_id=tenant_id,
            slug=slug,
            name=name or slug.title(),
        )
        db.add(w)
        db.commit()
        return w

    return _f


@pytest.fixture
def add_member(db):
    def _f(workspace_id: UUID, user_id: UUID, role: str = "member") -> WorkspaceMember:
        m = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
        db.add(m)
        db.commit()
        return m

    return _f


@pytest.fixture
def login_as(client, settings):
    """Plant a valid session cookie for a given user."""

    from api_gateway.auth.session import SessionPayload, encode_session

    def _f(user: User) -> str:
        now = int(time.time())
        payload = SessionPayload(
            user_id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            display_name=user.display_name,
            issued_at=now,
            expires_at=now + 3600,
        )
        token = encode_session(payload, secret=settings.secret_key)
        client.cookies.set(settings.session_cookie_name, token)
        return token

    return _f


@pytest.fixture
def audit_rows(db):
    """Helper: list audit rows currently in the DB."""

    def _f() -> list[dict[str, Any]]:
        rows = db.execute(AuditEventRow.__table__.select()).all()
        return [dict(r._mapping) for r in rows]

    return _f
