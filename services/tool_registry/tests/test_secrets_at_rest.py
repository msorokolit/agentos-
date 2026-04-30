"""Tool descriptors with sensitive fields are encrypted in the DB."""

from __future__ import annotations

import respx
from agenticos_shared.models import ToolRow


def test_create_encrypts_sensitive_descriptor_fields(client, db, workspace) -> None:
    body = {
        "workspace_id": str(workspace.id),
        "name": "my-jira",
        "kind": "http",
        "descriptor": {
            "endpoint": "https://api.example.com/v1",
            "headers": {
                "X-Api-Key": "sk-this-is-a-real-secret",
                "Content-Type": "application/json",
            },
        },
    }
    r = client.post("/tools", json=body)
    assert r.status_code == 201, r.text

    # The DB row's headers.X-Api-Key is stored as ciphertext.
    row = db.query(ToolRow).filter_by(name="my-jira").one()
    headers = row.descriptor["headers"]
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Api-Key"].startswith("v1:")
    assert "sk-this-is-a-real-secret" not in headers["X-Api-Key"]


def test_invoke_decrypts_sensitive_fields_for_outbound_call(client, workspace):
    """Round-trip: register with a secret header, then invoke and confirm
    the decrypted bearer reaches the upstream HTTP request."""

    body = {
        "workspace_id": str(workspace.id),
        "name": "my-api",
        "kind": "http",
        "descriptor": {
            "endpoint": "https://api.example.com/items",
            "headers": {"Authorization": "Bearer top-secret-bearer"},
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
            },
        },
    }
    r = client.post("/tools", json=body)
    assert r.status_code == 201
    tool_id = r.json()["id"]

    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://api.example.com/items").respond(200, json={"ok": True})
        r = client.post(
            "/invoke",
            json={
                "tool_id": tool_id,
                "workspace_id": str(workspace.id),
                "args": {"q": "x"},
            },
        )
    assert r.status_code == 200, r.text
    auth = route.calls[0].request.headers.get("authorization")
    assert auth == "Bearer top-secret-bearer"
