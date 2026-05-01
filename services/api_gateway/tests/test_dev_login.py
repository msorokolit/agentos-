"""Dev-only password-less login route."""

from __future__ import annotations


def _seed_alice(make_tenant, make_user):
    t = make_tenant(slug="acme")
    u = make_user(t.id, email="alice@agenticos.local", display_name="Alice")
    return t, u


def test_dev_login_mints_session_in_dev(client, make_tenant, make_user, monkeypatch):
    monkeypatch.setenv("AGENTICOS_ENV", "development")
    from api_gateway import settings as st

    st.get_settings.cache_clear()

    _seed_alice(make_tenant, make_user)
    r = client.get(
        "/api/v1/auth/dev/login",
        params={"email": "alice@agenticos.local", "return_to": "http://web/"},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    assert r.headers["location"] == "http://web/"
    assert "agos_session=" in r.headers.get("set-cookie", "")

    # Subsequent /api/v1/me with the cookie identifies Alice.
    cookie = r.cookies.get("agos_session")
    assert cookie is not None
    r2 = client.get("/api/v1/me", headers={"Cookie": f"agos_session={cookie}"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["email"] == "alice@agenticos.local"


def test_dev_login_404_in_production(client, make_tenant, make_user, monkeypatch):
    monkeypatch.setenv("AGENTICOS_ENV", "production")
    from api_gateway import settings as st

    st.get_settings.cache_clear()
    try:
        _seed_alice(make_tenant, make_user)
        r = client.get(
            "/api/v1/auth/dev/login",
            params={"email": "alice@agenticos.local"},
            follow_redirects=False,
        )
        assert r.status_code == 404, r.text
    finally:
        monkeypatch.setenv("AGENTICOS_ENV", "test")
        st.get_settings.cache_clear()


def test_dev_login_unknown_user(client, make_tenant, make_user, monkeypatch):
    monkeypatch.setenv("AGENTICOS_ENV", "development")
    from api_gateway import settings as st

    st.get_settings.cache_clear()
    _seed_alice(make_tenant, make_user)
    r = client.get(
        "/api/v1/auth/dev/login",
        params={"email": "nobody@agenticos.local"},
        follow_redirects=False,
    )
    assert r.status_code == 404, r.text
