def test_healthz(client) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["service"] == "llm-gateway"


def test_openapi(client) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = set(r.json()["paths"].keys())
    assert {
        "/admin/models",
        "/admin/models/{model_id}",
        "/admin/models/{model_id}/test",
        "/v1/chat/completions",
        "/v1/embeddings",
    } <= paths
