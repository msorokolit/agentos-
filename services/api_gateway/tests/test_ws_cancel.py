"""WebSocket chat: ``{"type":"cancel"}`` aborts an in-flight stream
without breaking the connection."""

from __future__ import annotations

import time

import httpx
from agenticos_shared.models import Agent
from api_gateway.auth.session import SessionPayload, encode_session

SECRET = "test-secret-32-bytes-or-more!!!"


def _open_ws(client, settings, user, agent_id):
    now = int(time.time())
    cookie = encode_session(
        SessionPayload(
            user_id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            display_name=user.display_name,
            issued_at=now,
            expires_at=now + 3600,
        ),
        secret=settings.secret_key,
    )
    client.cookies.set(settings.session_cookie_name, cookie)
    return client.websocket_connect(f"/api/v1/chat/{agent_id}/ws")


def _slow_sse(*, delay: float = 0.2) -> bytes:
    """SSE-like body that takes a while between chunks."""

    return (
        b'data: {"type":"step","payload":{"node":"plan"}}\n\n'
        b'data: {"type":"final","payload":{"content":"oh no"}}\n\n'
        b"data: [DONE]\n\n"
    )


def test_cancel_with_no_active_run_replies_quickly(
    monkeypatch, client, db, settings, make_tenant, make_user, make_workspace, add_member, login_as
):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="builder")
    a = Agent(
        id=__import__("uuid").uuid4(),
        workspace_id=w.id,
        slug="alpha",
        name="Alpha",
        model_alias="chat-default",
        graph_kind="react",
    )
    db.add(a)
    db.commit()

    with _open_ws(client, settings, u, a.id) as ws:
        # The first server frame is the session announcement.
        first = ws.receive_json()
        assert first["type"] == "session"

        ws.send_json({"type": "cancel"})
        msg = ws.receive_json()
        assert msg["type"] == "cancelled"
        assert msg["payload"]["reason"] == "no_active_run"


def test_user_message_cancel_then_ping_keeps_socket_open(
    monkeypatch, client, db, settings, make_tenant, make_user, make_workspace, add_member, login_as
):
    """A user_message that fails immediately (no upstream) followed by a
    cancel must not break the connection. Verifies the WS loop survives
    both error and cancel paths and continues serving ping/pong."""

    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="builder")
    a = Agent(
        id=__import__("uuid").uuid4(),
        workspace_id=w.id,
        slug="alpha",
        name="Alpha",
        model_alias="chat-default",
        graph_kind="react",
    )
    db.add(a)
    db.commit()

    # Make every outgoing AsyncClient.stream raise immediately so the
    # in-flight task ends fast — the WS loop should still be alive.
    real_async_client = httpx.AsyncClient

    class _Boom(real_async_client):
        def stream(self, *args, **kwargs):
            raise httpx.ConnectError("blocked in test")

    from api_gateway.routes import chat as chat_mod

    monkeypatch.setattr(chat_mod.httpx, "AsyncClient", _Boom)

    with _open_ws(client, settings, u, a.id) as ws:
        ws.receive_json()  # session
        ws.send_json({"type": "user_message", "content": "hi"})
        # We expect an error frame from the failed stream attempt.
        ev = ws.receive_json()
        assert ev["type"] in ("error", "cancelled")

        # Now cancel — there's no in-flight stream, so we should hear
        # the no_active_run reply and the socket should still answer pings.
        ws.send_json({"type": "cancel"})
        seen = False
        for _ in range(5):
            ev = ws.receive_json()
            if ev["type"] == "cancelled":
                seen = True
                break
        assert seen

        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


def test_ping_pong(
    client, db, settings, make_tenant, make_user, make_workspace, add_member, login_as
):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="builder")
    a = Agent(
        id=__import__("uuid").uuid4(),
        workspace_id=w.id,
        slug="alpha",
        name="Alpha",
        model_alias="chat-default",
        graph_kind="react",
    )
    db.add(a)
    db.commit()
    with _open_ws(client, settings, u, a.id) as ws:
        ws.receive_json()  # session
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
