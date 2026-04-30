"""End-to-end /run + /run/stream via the FastAPI app."""

from __future__ import annotations

from uuid import uuid4

import pytest


class _StubProxies:
    def __init__(self, llm, tools, knowledge):
        self.llm = llm
        self.tools = tools
        self.knowledge = knowledge


@pytest.fixture
def stubbed_proxies(monkeypatch, StubLLMCls, StubToolsCls, StubKnowledgeCls):
    """Replace get_proxies + get_publish with deterministic stubs."""

    class Holder:
        llm = StubLLMCls()
        tools = StubToolsCls()
        knowledge = StubKnowledgeCls()

    holder = Holder()

    from agent_runtime import routes as routes_mod
    from agent_runtime import state as st

    monkeypatch.setattr(st, "get_proxies", lambda: (holder.llm, holder.tools, holder.knowledge))
    monkeypatch.setattr(st, "get_publish", lambda: None)
    monkeypatch.setattr(
        routes_mod,
        "get_proxies",
        lambda: (holder.llm, holder.tools, holder.knowledge),
    )
    monkeypatch.setattr(routes_mod, "get_publish", lambda: None)
    return holder


def test_run_persists_messages(
    client, db, workspace, make_agent, make_session, stubbed_proxies
) -> None:
    a = make_agent(workspace.id)
    s = make_session(workspace.id, a.id)

    stubbed_proxies.llm.responses = [
        {
            "choices": [{"message": {"role": "assistant", "content": "Hi there."}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2},
        }
    ]

    r = client.post(
        "/run",
        json={
            "agent_id": str(a.id),
            "session_id": str(s.id),
            "user_message": "hello",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["final_message"] == "Hi there."

    from agenticos_shared.models import Message

    rows = db.query(Message).filter_by(session_id=s.id).all()
    roles = [m.role for m in rows]
    assert "user" in roles
    assert "assistant" in roles


def test_run_unknown_agent_404(client, workspace, make_agent, make_session) -> None:
    s_id = uuid4()
    r = client.post(
        "/run",
        json={
            "agent_id": str(uuid4()),
            "session_id": str(s_id),
            "user_message": "hi",
        },
    )
    assert r.status_code == 404


def test_run_stream_emits_sse(
    client, db, workspace, make_agent, make_session, stubbed_proxies
) -> None:
    a = make_agent(workspace.id)
    s = make_session(workspace.id, a.id)

    stubbed_proxies.llm.responses = [
        {
            "choices": [{"message": {"role": "assistant", "content": "stream-hi"}}],
            "usage": {},
        }
    ]

    with client.stream(
        "POST",
        "/run/stream",
        json={
            "agent_id": str(a.id),
            "session_id": str(s.id),
            "user_message": "go",
        },
    ) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        chunks: list[str] = []
        for line in r.iter_lines():
            if line.startswith("data: "):
                chunks.append(line[len("data: ") :])
                if line.endswith("[DONE]"):
                    break
    assert any("stream-hi" in c for c in chunks)
    # Final assistant message persisted.
    from agenticos_shared.models import Message

    final_assistant = (
        db.query(Message)
        .filter_by(session_id=s.id, role="assistant")
        .order_by(Message.created_at.desc())
        .first()
    )
    assert final_assistant is not None
    assert final_assistant.content == "stream-hi"
