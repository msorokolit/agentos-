"""End-to-end invoker tests via the FastAPI app."""

from __future__ import annotations


def _create_builtin(client, workspace, name: str = "http_get", scopes=None) -> str:
    body = {
        "workspace_id": str(workspace.id),
        "name": name,
        "kind": "builtin",
        "descriptor": {
            "name": name,
            "description": "x",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
        "scopes": scopes or [],
    }
    r = client.post("/tools", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_invoke_validates_args_against_schema(client, workspace):
    tool_id = _create_builtin(client, workspace)
    r = client.post(
        "/invoke",
        json={
            "tool_id": tool_id,
            "workspace_id": str(workspace.id),
            "args": {},  # missing required `url`
        },
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


def test_invoke_unknown_tool_404(client, workspace):
    r = client.post(
        "/invoke",
        json={
            "name": "no-such-tool",
            "workspace_id": str(workspace.id),
            "args": {},
        },
    )
    assert r.status_code == 404


def test_invoke_disabled_tool_validation_error(client, workspace):
    tool_id = _create_builtin(client, workspace)
    client.patch(f"/tools/{tool_id}", json={"enabled": False})
    r = client.post(
        "/invoke",
        json={
            "tool_id": tool_id,
            "workspace_id": str(workspace.id),
            "args": {"url": "https://x"},
        },
    )
    assert r.status_code == 422


def test_invoke_http_get_succeeds_with_mock(client, workspace):
    import respx

    tool_id = _create_builtin(client, workspace)
    with respx.mock() as router:
        router.get("https://example.com/hi").respond(200, text="ok")
        r = client.post(
            "/invoke",
            json={
                "tool_id": tool_id,
                "workspace_id": str(workspace.id),
                "args": {"url": "https://example.com/hi"},
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["result"]["status"] == 200


def test_builtin_alias_resolves_via_descriptor(client, workspace):
    """A builtin registered under a friendly name (``web_get``) must
    still dispatch to the underlying builtin declared in the
    descriptor (``http_get``)."""

    import respx

    body = {
        "workspace_id": str(workspace.id),
        "name": "web_get",  # user-chosen alias
        "kind": "builtin",
        "descriptor": {
            "builtin": "http_get",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    }
    r = client.post("/tools", json=body)
    assert r.status_code == 201, r.text
    tool_id = r.json()["id"]

    with respx.mock() as router:
        router.get("https://example.com/").respond(200, text="hello")
        r = client.post(
            "/invoke",
            json={
                "tool_id": tool_id,
                "workspace_id": str(workspace.id),
                "args": {"url": "https://example.com/"},
            },
        )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["ok"] is True, out
    assert out["result"]["status"] == 200
