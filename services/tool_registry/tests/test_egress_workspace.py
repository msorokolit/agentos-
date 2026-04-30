"""Per-workspace egress allow-list merges with the global one."""

from __future__ import annotations

import respx


def _make_http_tool(client, workspace, *, allow_global_only_target: bool = False):
    """Register an HTTP tool that points at a host the global config blocks."""

    body = {
        "workspace_id": str(workspace.id),
        "name": "ping-external",
        "kind": "http",
        "descriptor": {
            "endpoint": "https://api.example.com/ping",
            "method": "GET",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    }
    r = client.post("/tools", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_workspace_allow_list_unblocks_a_host(client, workspace, monkeypatch):
    """The global allow-list excludes ``api.example.com`` but the
    workspace passes it via ``extra_allow_hosts``."""

    monkeypatch.setenv("EGRESS_ALLOW_HOSTS", '["only.allowed.example.com"]')
    from tool_registry import settings as st

    st.get_settings.cache_clear()

    tool_id = _make_http_tool(client, workspace)
    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.example.com/ping").respond(200, text="ok")
        r = client.post(
            "/invoke",
            json={
                "tool_id": tool_id,
                "workspace_id": str(workspace.id),
                "args": {},
                "extra_allow_hosts": ["api.example.com"],
            },
        )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_blocked_when_neither_list_allows(client, workspace, monkeypatch):
    monkeypatch.setenv("EGRESS_ALLOW_HOSTS", '["only.allowed.example.com"]')
    from tool_registry import settings as st

    st.get_settings.cache_clear()

    tool_id = _make_http_tool(client, workspace)
    r = client.post(
        "/invoke",
        json={
            "tool_id": tool_id,
            "workspace_id": str(workspace.id),
            "args": {},
            "extra_allow_hosts": ["other.example.com"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "egress" in (body["error"] or "").lower()


def test_workspace_wildcard(client, workspace, monkeypatch):
    monkeypatch.setenv("EGRESS_ALLOW_HOSTS", "[]")
    from tool_registry import settings as st

    st.get_settings.cache_clear()

    tool_id = _make_http_tool(client, workspace)
    with respx.mock(assert_all_called=True) as router:
        router.get("https://api.example.com/ping").respond(200, text="ok")
        r = client.post(
            "/invoke",
            json={
                "tool_id": tool_id,
                "workspace_id": str(workspace.id),
                "args": {},
                "extra_allow_hosts": ["*.example.com"],
            },
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
