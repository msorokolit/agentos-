def test_healthz(client) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200


def test_builtins_list(client) -> None:
    r = client.get("/builtins")
    assert r.status_code == 200
    names = {b["name"] for b in r.json()}
    assert {"http_get", "rag_search"} <= names
