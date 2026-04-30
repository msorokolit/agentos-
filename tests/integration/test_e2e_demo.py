"""End-to-end smoke: workspace → tool → agent through the full stack.

Tests the api-gateway proxying real ASGI calls into the other services.
External dependencies (Ollama, OPA) are mocked with respx.
"""

from __future__ import annotations

import time
from uuid import uuid4

import pytest
import respx
from agenticos_shared.models import Tenant, User
from api_gateway.auth.session import SessionPayload, encode_session

SECRET = "test-secret-32-bytes-or-more!!!"


@pytest.fixture
def alice(shared_session):
    t = Tenant(id=uuid4(), slug="acme", name="Acme")
    u = User(
        id=uuid4(),
        tenant_id=t.id,
        email="alice@agenticos.local",
        display_name="Alice",
        is_superuser=True,
    )
    shared_session.add_all([t, u])
    shared_session.commit()
    return u


@pytest.fixture
def login(api_client, alice):
    now = int(time.time())
    cookie = encode_session(
        SessionPayload(
            user_id=alice.id,
            tenant_id=alice.tenant_id,
            email=alice.email,
            display_name=alice.display_name,
            issued_at=now,
            expires_at=now + 3600,
        ),
        secret=SECRET,
    )
    api_client.cookies.set("agos_session", cookie)
    return alice


def test_demo_flow_through_api_gateway(api_client, login, shared_session):
    # 1. Create a workspace.
    r = api_client.post("/api/v1/workspaces", json={"name": "Demo", "slug": "demo"})
    assert r.status_code == 201, r.text
    ws_id = r.json()["id"]

    # 2. Register a built-in tool (proxied through to tool-registry).
    builtins = api_client.get("/api/v1/builtins").json()
    http_get = next(b for b in builtins if b["name"] == "http_get")
    r = api_client.post(
        f"/api/v1/workspaces/{ws_id}/tools",
        json={
            "name": "http_get",
            "kind": "builtin",
            "descriptor": http_get,
            "scopes": ["safe"],
        },
    )
    assert r.status_code == 201, r.text

    # 3. Register a chat model alias (proxied through to llm-gateway).
    r = api_client.post(
        "/api/v1/admin/models",
        json={
            "alias": "chat-default",
            "provider": "ollama",
            "endpoint": "http://ollama:11434",
            "model_name": "qwen2.5:7b-instruct",
            "kind": "chat",
        },
    )
    assert r.status_code == 201, r.text

    # 4. Upload a document via knowledge-svc proxy (simple text payload).
    r = api_client.post(
        f"/api/v1/workspaces/{ws_id}/documents",
        files={"file": ("note.txt", b"Hello, world!", "text/plain")},
    )
    # We don't have an embedder mounted here so ingestion may fail (502)
    # — both 201 and 502 are acceptable; what matters is RBAC + routing
    # didn't blow up.
    assert r.status_code in (201, 502, 422), r.text

    # 5. Create an agent.
    r = api_client.post(
        f"/api/v1/workspaces/{ws_id}/agents",
        json={
            "name": "Demo",
            "slug": "demo",
            "system_prompt": "concise.",
            "model_alias": "chat-default",
            "tool_ids": [],
        },
    )
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]

    # 6. Run the agent — Ollama upstream is mocked.
    with respx.mock(assert_all_called=False) as router:
        router.post("http://ollama:11434/api/chat").respond(
            json={
                "message": {"role": "assistant", "content": "Hi from demo!"},
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 4,
                "eval_count": 3,
            }
        )
        r = api_client.post(
            f"/api/v1/workspaces/{ws_id}/agents/{agent_id}/run",
            json={"user_message": "say hi"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["final_message"] == "Hi from demo!"
    assert body["session_id"]

    # 7. Audit log records all of it.
    r = api_client.get(f"/api/v1/workspaces/{ws_id}/audit?limit=50")
    assert r.status_code == 200
    actions = {row["action"] for row in r.json()}
    # model.create is a tenant-scoped audit event (no workspace_id) so it is
    # not surfaced through this workspace-scoped endpoint.
    assert {"workspace.create", "tool.create", "agent.create", "agent.run"} <= actions
