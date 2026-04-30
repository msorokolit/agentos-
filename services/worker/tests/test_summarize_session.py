"""End-to-end test for the session summariser job."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import respx
from agenticos_shared import db as shared_db
from agenticos_shared.models import (
    Agent,
    Base,
    Message,
    Tenant,
    Workspace,
)
from agenticos_shared.models import (
    Session as SessionRow,
)
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


def _seed_session(db_engine) -> tuple[UUID, UUID]:
    """Seed fixtures and return (workspace_id, session_id) as detached UUIDs."""

    sm = sessionmaker(bind=db_engine, future=True)
    with sm() as db:
        t = Tenant(id=uuid4(), slug="acme", name="Acme")
        db.add(t)
        db.flush()
        w_id = uuid4()
        db.add(Workspace(id=w_id, tenant_id=t.id, slug="default", name="Default"))
        db.flush()
        a_id = uuid4()
        db.add(
            Agent(
                id=a_id,
                workspace_id=w_id,
                slug="alpha",
                name="Alpha",
                model_alias="chat-default",
                graph_kind="react",
            )
        )
        db.flush()
        s_id = uuid4()
        db.add(SessionRow(id=s_id, workspace_id=w_id, agent_id=a_id))
        db.flush()
        db.add_all(
            [
                Message(
                    id=uuid4(),
                    session_id=s_id,
                    role="user",
                    content="When was AgenticOS founded?",
                    citations=[],
                ),
                Message(
                    id=uuid4(),
                    session_id=s_id,
                    role="assistant",
                    content="Per the docs, AgenticOS was founded in 2026.",
                    citations=[],
                ),
            ]
        )
        db.commit()
        return w_id, s_id


@pytest.mark.asyncio
async def test_summarize_session_happy_path(db_engine, monkeypatch):
    monkeypatch.setenv("AGENTICOS_ENV", "test")
    from worker import settings as st

    st.get_settings.cache_clear()

    w_id, s_id = _seed_session(db_engine)

    with respx.mock(assert_all_called=True) as router:
        router.post("http://llm-gateway:8081/v1/chat/completions").respond(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": "chat-default",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "AgenticOS was founded in 2026 according to the docs.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6},
            },
        )
        memory_route = router.post("http://memory-svc:8085/items").respond(
            201,
            json={
                "id": str(uuid4()),
                "workspace_id": str(w_id),
                "scope": "session",
                "owner_id": str(s_id),
                "key": f"summary:{s_id}",
                "value": {"session_id": str(s_id)},
                "summary": "AgenticOS was founded in 2026 according to the docs.",
                "has_embedding": True,
                "expires_at": None,
                "created_at": "2026-04-30T00:00:00Z",
                "updated_at": "2026-04-30T00:00:00Z",
            },
        )
        from worker.jobs.summarize_session import summarize_session

        out = await summarize_session({}, str(s_id))

    assert out["ok"] is True
    assert "founded in 2026" in out["summary"].lower()

    body = memory_route.calls[0].request.read().decode()
    import json as _json

    payload = _json.loads(body)
    assert payload["scope"] == "session"
    assert payload["embed"] is True
    assert payload["owner_id"] == str(s_id)
    assert payload["key"] == f"summary:{s_id}"


@pytest.mark.asyncio
async def test_summarize_session_unknown_session(db_engine, monkeypatch):
    monkeypatch.setenv("AGENTICOS_ENV", "test")
    from worker import settings as st

    st.get_settings.cache_clear()
    from worker.jobs.summarize_session import summarize_session

    out = await summarize_session({}, str(uuid4()))
    assert out == {"ok": False, "reason": "session not found"}


@pytest.mark.asyncio
async def test_summarize_session_llm_failure(db_engine, monkeypatch):
    monkeypatch.setenv("AGENTICOS_ENV", "test")
    from worker import settings as st

    st.get_settings.cache_clear()
    _, s_id = _seed_session(db_engine)

    with respx.mock() as router:
        router.post("http://llm-gateway:8081/v1/chat/completions").respond(500, text="boom")
        from worker.jobs.summarize_session import summarize_session

        out = await summarize_session({}, str(s_id))
    assert out == {"ok": False, "reason": "llm failed"}
