"""End-to-end /run + /run/stream via the FastAPI app."""

from __future__ import annotations

from uuid import uuid4

import pytest


class _StubProxies:
    def __init__(self, llm, tools, knowledge):
        self.llm = llm
        self.tools = tools
        self.knowledge = knowledge


class StubMemory:
    def __init__(self) -> None:
        self.appends: list[dict] = []
        self._stm: dict = {}

    async def append_short_term(self, *, workspace_id, session_id, role, content):
        self.appends.append({"role": role, "content": content})
        self._stm.setdefault((workspace_id, session_id), []).append(
            {"role": role, "content": content}
        )

    async def get_short_term(self, *, workspace_id, session_id):
        return list(self._stm.get((workspace_id, session_id), []))


@pytest.fixture
def stubbed_proxies(monkeypatch, StubLLMCls, StubToolsCls, StubKnowledgeCls):
    """Replace get_proxies + get_publish with deterministic stubs."""

    class Holder:
        llm = StubLLMCls()
        tools = StubToolsCls()
        knowledge = StubKnowledgeCls()
        memory = StubMemory()

    holder = Holder()

    from agent_runtime import routes as routes_mod
    from agent_runtime import state as st

    proxies = (holder.llm, holder.tools, holder.knowledge, holder.memory)
    monkeypatch.setattr(st, "get_proxies", lambda: proxies)
    monkeypatch.setattr(st, "get_publish", lambda: None)
    monkeypatch.setattr(routes_mod, "get_proxies", lambda: proxies)
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


def test_run_uses_short_term_history_then_persists(
    client, db, workspace, make_agent, make_session, stubbed_proxies
) -> None:
    a = make_agent(workspace.id)
    s = make_session(workspace.id, a.id)

    # Pre-seed short-term so the runtime should pick history from it.
    stubbed_proxies.memory._stm[(workspace.id, s.id)] = [
        {"role": "user", "content": "earlier-q"},
        {"role": "assistant", "content": "earlier-a"},
    ]

    stubbed_proxies.llm.responses = [
        {
            "choices": [{"message": {"role": "assistant", "content": "the answer"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
    ]

    r = client.post(
        "/run",
        json={
            "agent_id": str(a.id),
            "session_id": str(s.id),
            "user_message": "follow-up",
        },
    )
    assert r.status_code == 200, r.text

    # The earlier history was passed into the LLM as messages.
    chat_payload = stubbed_proxies.llm.calls[0]
    contents = [m.get("content", "") for m in chat_payload["messages"]]
    assert any("earlier-q" in c for c in contents)
    assert any("earlier-a" in c for c in contents)

    # Both the new user msg and the assistant final were appended to STM.
    stm_after = stubbed_proxies.memory._stm[(workspace.id, s.id)]
    roles = [m["role"] for m in stm_after]
    contents_after = [m["content"] for m in stm_after]
    assert "follow-up" in contents_after
    assert "the answer" in contents_after
    assert roles[-2:] == ["user", "assistant"]


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
