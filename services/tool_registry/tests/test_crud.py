"""Tool registry CRUD."""

from __future__ import annotations


def test_create_list_update_delete(client, workspace):
    body = {
        "workspace_id": str(workspace.id),
        "name": "http_get",
        "kind": "builtin",
        "descriptor": {"name": "http_get", "description": "fetch", "parameters": {}},
        "scopes": ["safe"],
    }
    r = client.post("/tools", json=body)
    assert r.status_code == 201, r.text
    tool_id = r.json()["id"]

    r2 = client.get(f"/tools?workspace_id={workspace.id}")
    assert r2.status_code == 200
    assert any(t["name"] == "http_get" for t in r2.json())

    r3 = client.patch(f"/tools/{tool_id}", json={"enabled": False})
    assert r3.status_code == 200
    assert r3.json()["enabled"] is False

    r4 = client.delete(f"/tools/{tool_id}")
    assert r4.status_code == 204


def test_duplicate_name_in_workspace_conflicts(client, workspace):
    body = {
        "workspace_id": str(workspace.id),
        "name": "http_get",
        "kind": "builtin",
        "descriptor": {},
    }
    assert client.post("/tools", json=body).status_code == 201
    assert client.post("/tools", json=body).status_code == 409
