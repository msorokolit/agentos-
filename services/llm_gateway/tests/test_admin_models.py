"""Admin CRUD on the model registry."""

from __future__ import annotations


def _new_model(alias: str = "chat-default", kind: str = "chat") -> dict:
    return {
        "alias": alias,
        "provider": "ollama",
        "endpoint": "http://ollama:11434",
        "model_name": "qwen2.5:7b-instruct",
        "kind": kind,
    }


def test_create_then_list(client) -> None:
    r = client.post("/admin/models", json=_new_model())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["alias"] == "chat-default"
    assert body["enabled"] is True

    r = client.get("/admin/models")
    assert r.status_code == 200
    assert any(m["alias"] == "chat-default" for m in r.json())


def test_create_duplicate_alias_conflict(client) -> None:
    r1 = client.post("/admin/models", json=_new_model())
    assert r1.status_code == 201
    r2 = client.post("/admin/models", json=_new_model())
    assert r2.status_code == 409


def test_update_and_delete(client) -> None:
    r = client.post("/admin/models", json=_new_model())
    mid = r.json()["id"]

    r2 = client.patch(f"/admin/models/{mid}", json={"enabled": False, "model_name": "foo"})
    assert r2.status_code == 200
    assert r2.json()["enabled"] is False
    assert r2.json()["model_name"] == "foo"

    r3 = client.delete(f"/admin/models/{mid}")
    assert r3.status_code == 204

    r4 = client.get("/admin/models")
    assert r4.json() == []
