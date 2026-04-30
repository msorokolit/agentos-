"""tool_registry: /metrics exposes tool_invocations_total after invoke."""

from __future__ import annotations

import respx


def _create_builtin(client, workspace) -> str:
    body = {
        "workspace_id": str(workspace.id),
        "name": "http_get",
        "kind": "builtin",
        "descriptor": {
            "name": "http_get",
            "description": "x",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
        "scopes": ["safe"],
    }
    r = client.post("/tools", json=body)
    return r.json()["id"]


def test_invoke_records_metric(client, workspace) -> None:
    tool_id = _create_builtin(client, workspace)
    with respx.mock() as router:
        router.get("https://example.com/x").respond(200, text="ok")
        r = client.post(
            "/invoke",
            json={
                "tool_id": tool_id,
                "workspace_id": str(workspace.id),
                "args": {"url": "https://example.com/x"},
            },
        )
    assert r.status_code == 200

    body = client.get("/metrics").text
    assert "tool_invocations_total" in body
    assert 'tool_invocations_total{kind="builtin",ok="true",tool="http_get"}' in body
