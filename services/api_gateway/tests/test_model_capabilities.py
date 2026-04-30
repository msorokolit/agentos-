"""Agent create/update is gated on the model's declared capabilities."""

from __future__ import annotations

from uuid import uuid4

import respx
from agenticos_shared.models import ToolRow


def _seed_tool(db, workspace_id) -> str:
    t = ToolRow(
        id=uuid4(),
        workspace_id=workspace_id,
        name=f"t-{uuid4().hex[:6]}",
        kind="builtin",
        descriptor={},
        scopes=[],
        enabled=True,
    )
    db.add(t)
    db.commit()
    return str(t.id)

CHAT_NO_TOOLS = {
    "id": str(uuid4()),
    "alias": "chat-no-tools",
    "provider": "ollama",
    "endpoint": "http://ollama:11434",
    "model_name": "small",
    "kind": "chat",
    "capabilities": {"tool_use": False, "context_window": 4096},
    "default_params": {},
    "enabled": True,
}
CHAT_WITH_TOOLS = {
    "id": str(uuid4()),
    "alias": "chat-tools",
    "provider": "ollama",
    "endpoint": "http://ollama:11434",
    "model_name": "qwen",
    "kind": "chat",
    "capabilities": {"tool_use": True, "context_window": 32768},
    "default_params": {},
    "enabled": True,
}
EMBED = {
    "id": str(uuid4()),
    "alias": "embed-default",
    "provider": "ollama",
    "endpoint": "http://ollama:11434",
    "model_name": "nomic",
    "kind": "embedding",
    "capabilities": {},
    "default_params": {},
    "enabled": True,
}


def _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id, email="b@x")
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="builder")
    login_as(u)
    return u, w


def _mock_models(router, models):
    router.get("http://llm-gateway:8081/admin/models").respond(json=models)


def _clear_caps_cache():
    from api_gateway import model_capabilities as mc

    mc._clear_cache()


def test_create_with_tools_requires_tool_use_capability(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    _clear_caps_cache()
    with respx.mock(assert_all_called=True) as router:
        _mock_models(router, [CHAT_NO_TOOLS])
        r = client.post(
            f"/api/v1/workspaces/{w.id}/agents",
            json={
                "name": "x",
                "slug": "alpha",
                "model_alias": "chat-no-tools",
                "tool_ids": [str(uuid4())],
            },
        )
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert "tool_use" in body["detail"]


def test_create_with_tools_passes_when_capable(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    _clear_caps_cache()
    tool_id = _seed_tool(db, w.id)
    with respx.mock() as router:
        _mock_models(router, [CHAT_WITH_TOOLS])
        r = client.post(
            f"/api/v1/workspaces/{w.id}/agents",
            json={
                "name": "x",
                "slug": "alpha",
                "model_alias": "chat-tools",
                "tool_ids": [tool_id],
            },
        )
    assert r.status_code == 201, r.text


def test_create_unknown_alias_404(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    _clear_caps_cache()
    with respx.mock() as router:
        _mock_models(router, [CHAT_WITH_TOOLS])
        r = client.post(
            f"/api/v1/workspaces/{w.id}/agents",
            json={"name": "x", "slug": "alpha", "model_alias": "no-such-alias"},
        )
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_create_with_embedding_alias_rejected(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    _clear_caps_cache()
    with respx.mock() as router:
        _mock_models(router, [EMBED])
        r = client.post(
            f"/api/v1/workspaces/{w.id}/agents",
            json={"name": "x", "slug": "alpha", "model_alias": "embed-default"},
        )
    assert r.status_code == 422
    assert "chat model" in r.json()["detail"]


def test_create_falls_back_to_no_op_when_registry_offline(
    client, db, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    _clear_caps_cache()
    tool_id = _seed_tool(db, w.id)
    with respx.mock() as router:
        router.get("http://llm-gateway:8081/admin/models").respond(503, text="unavailable")
        r = client.post(
            f"/api/v1/workspaces/{w.id}/agents",
            json={
                "name": "x",
                "slug": "alpha",
                "model_alias": "anything",
                "tool_ids": [tool_id],
            },
        )
    # We don't block agent CRUD on a transient registry outage.
    assert r.status_code == 201, r.text


def test_update_recomputes_capabilities(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_builder(client, make_tenant, make_user, make_workspace, add_member, login_as)
    _clear_caps_cache()
    with respx.mock() as router:
        _mock_models(router, [CHAT_NO_TOOLS, CHAT_WITH_TOOLS])
        # Create on the no-tools alias with no tool_ids — fine.
        r = client.post(
            f"/api/v1/workspaces/{w.id}/agents",
            json={"name": "x", "slug": "alpha", "model_alias": "chat-no-tools"},
        )
        assert r.status_code == 201, r.text
        agent_id = r.json()["id"]

        # Now try to bind tools without switching the model — fail.
        r = client.patch(
            f"/api/v1/workspaces/{w.id}/agents/{agent_id}",
            json={"tool_ids": [str(uuid4())]},
        )
    assert r.status_code == 422
    assert "tool_use" in r.json()["detail"]
