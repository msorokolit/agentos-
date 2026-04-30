"""POST /workspaces/{id}/collections/{id}/search — collection-scoped search."""

from __future__ import annotations

from uuid import uuid4

import respx


def _login_member(client, make_tenant, make_user, make_workspace, add_member, login_as):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")
    add_member(w.id, u.id, role="member")
    login_as(u)
    return u, w


def test_collection_search_injects_collection_id(
    client, make_tenant, make_user, make_workspace, add_member, login_as
):
    _, w = _login_member(client, make_tenant, make_user, make_workspace, add_member, login_as)
    coll_id = uuid4()

    upstream = {"query": "x", "hits": []}
    with respx.mock(assert_all_called=True) as router:
        route = router.post("http://knowledge-svc:8084/search").respond(json=upstream)
        r = client.post(
            f"/api/v1/workspaces/{w.id}/collections/{coll_id}/search",
            json={"query": "x", "top_k": 3},
        )
    assert r.status_code == 200, r.text
    sent = route.calls[0].request.read().decode()
    assert str(w.id) in sent
    assert str(coll_id) in sent
    # ``top_k`` survives.
    assert '"top_k": 3' in sent or '"top_k":3' in sent


def test_collection_search_requires_membership(
    client, make_tenant, make_user, make_workspace, login_as
):
    t = make_tenant()
    u = make_user(t.id)
    w = make_workspace(t.id, slug="default")  # u is not a member
    login_as(u)
    r = client.post(
        f"/api/v1/workspaces/{w.id}/collections/{uuid4()}/search",
        json={"query": "x"},
    )
    assert r.status_code == 403
