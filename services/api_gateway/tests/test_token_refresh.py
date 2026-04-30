"""POST /api/v1/auth/token/refresh — rotate a still-valid session cookie."""

from __future__ import annotations

import time

from api_gateway.auth.session import SessionPayload, decode_session, encode_session

SECRET = "test-secret-32-bytes-or-more!!!"


def test_refresh_unauthenticated_401(client) -> None:
    r = client.post("/api/v1/auth/token/refresh")
    assert r.status_code == 401


def test_refresh_rotates_cookie_and_keeps_principal(
    client, settings, make_tenant, make_user, login_as
) -> None:
    t = make_tenant()
    u = make_user(t.id)
    login_as(u)

    # The login_as fixture put one cookie into the jar; record it.
    initial_cookies = list(client.cookies.jar)
    initial = next(c for c in initial_cookies if c.name == settings.session_cookie_name).value
    assert initial

    # Sleep a beat so issued_at differs.
    time.sleep(1)
    r = client.post("/api/v1/auth/token/refresh")
    assert r.status_code == 200
    assert r.json() == {"refreshed": True}
    # The refresh response carries a fresh Set-Cookie; pull it from headers.
    set_cookie = r.headers["set-cookie"]
    assert settings.session_cookie_name in set_cookie
    rotated = set_cookie.split(f"{settings.session_cookie_name}=", 1)[1].split(";", 1)[0]
    assert rotated and rotated != initial

    before = decode_session(initial, secret=settings.secret_key)
    after = decode_session(rotated, secret=settings.secret_key)
    assert before.user_id == after.user_id
    assert after.issued_at >= before.issued_at
    assert after.expires_at > before.expires_at


def test_refresh_expired_cookie_rejected(client, settings, make_tenant, make_user) -> None:
    t = make_tenant()
    u = make_user(t.id)

    now = int(time.time())
    expired = encode_session(
        SessionPayload(
            user_id=u.id,
            tenant_id=u.tenant_id,
            email=u.email,
            display_name=u.display_name,
            issued_at=now - 7200,
            expires_at=now - 60,
        ),
        secret=settings.secret_key,
    )
    client.cookies.set(settings.session_cookie_name, expired)
    r = client.post("/api/v1/auth/token/refresh")
    assert r.status_code == 401
