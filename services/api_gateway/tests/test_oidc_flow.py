"""End-to-end OIDC flow with a mocked IdP.

We mint a real RSA key pair, sign a JWT as the IdP, and serve discovery +
JWKS + token endpoints with `respx`.
"""

from __future__ import annotations

import time
from uuid import UUID

import pytest
import respx
from agenticos_shared.models import Tenant, User
from api_gateway.auth import oidc as oidc_mod
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from sqlalchemy import select

ISSUER = "http://idp.test/realms/agenticos"
CLIENT_ID = "agenticos-web"
CLIENT_SECRET = "dev-client-secret"
REDIRECT_URI = "http://localhost:8080/api/v1/auth/oidc/callback"


@pytest.fixture
def rsa_keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_numbers = priv.public_key().public_numbers()

    def _b64(n: int) -> str:
        import base64

        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    jwk = {
        "kty": "RSA",
        "kid": "test-key",
        "use": "sig",
        "alg": "RS256",
        "n": _b64(pub_numbers.n),
        "e": _b64(pub_numbers.e),
    }
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return pem, jwk


@pytest.fixture(autouse=True)
def _clear_caches():
    oidc_mod._clear_caches()
    yield
    oidc_mod._clear_caches()


@pytest.fixture
def configure_oidc(monkeypatch):
    """Point the api-gateway at our mock IdP."""

    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("OIDC_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("OIDC_REDIRECT_URI", REDIRECT_URI)
    monkeypatch.setenv("AUTO_PROVISION_TENANT", "acme")
    from api_gateway.settings import get_settings

    get_settings.cache_clear()


def _mock_idp(jwk: dict) -> respx.MockRouter:
    router = respx.mock(assert_all_called=False)
    router.get(f"{ISSUER}/.well-known/openid-configuration").respond(
        json={
            "issuer": ISSUER,
            "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
            "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
            "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
        }
    )
    router.get(f"{ISSUER}/protocol/openid-connect/certs").respond(json={"keys": [jwk]})
    return router


def _make_id_token(*, priv_pem: str, kid: str, nonce: str, email: str = "alice@idp.test") -> str:
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "user-123",
        "email": email,
        "email_verified": True,
        "name": "Alice IdP",
        "nonce": nonce,
        "iat": now,
        "exp": now + 600,
    }
    return jwt.encode(payload, priv_pem, algorithm="RS256", headers={"kid": kid})


def test_login_redirects_to_idp(client, configure_oidc, rsa_keypair):
    _, jwk = rsa_keypair
    router = _mock_idp(jwk)
    with router:
        r = client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith(f"{ISSUER}/protocol/openid-connect/auth?")
    assert "state=" in location
    assert "nonce=" in location
    # cookies must include state + nonce
    assert "agos_oidc_state" in r.cookies
    assert "agos_oidc_nonce" in r.cookies


def test_login_json_mode(client, configure_oidc, rsa_keypair):
    _, jwk = rsa_keypair
    with _mock_idp(jwk):
        r = client.get("/api/v1/auth/oidc/login?json=true")
    assert r.status_code == 200
    body = r.json()
    assert body["authorize_url"].startswith(ISSUER)
    assert body["state"]


def test_callback_creates_user_and_session(client, db, configure_oidc, rsa_keypair):
    priv_pem, jwk = rsa_keypair

    # Step 1: hit /login to plant state + nonce cookies.
    with _mock_idp(jwk):
        r = client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    state = client.cookies.get("agos_oidc_state")
    nonce = client.cookies.get("agos_oidc_nonce")
    assert state and nonce

    # Step 2: mock the token endpoint to return our signed id_token.
    id_token = _make_id_token(priv_pem=priv_pem, kid=jwk["kid"], nonce=nonce)
    router = _mock_idp(jwk)
    router.post(f"{ISSUER}/protocol/openid-connect/token").respond(
        json={
            "access_token": "at-x",
            "id_token": id_token,
            "token_type": "Bearer",
            "expires_in": 600,
        }
    )

    with router:
        r = client.get(
            f"/api/v1/auth/oidc/callback?code=abc&state={state}",
            follow_redirects=False,
        )
    assert r.status_code == 302, r.text
    # session cookie now set
    session_cookie = client.cookies.get("agos_session")
    assert session_cookie

    # User + tenant auto-provisioned.
    tenant = db.execute(select(Tenant).where(Tenant.slug == "acme")).scalar_one()
    user = db.execute(
        select(User).where(User.email == "alice@idp.test", User.tenant_id == tenant.id)
    ).scalar_one()
    assert user.oidc_sub == "user-123"
    assert user.display_name == "Alice IdP"

    # /me works now.
    me = client.get("/api/v1/me")
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "alice@idp.test"
    assert UUID(me.json()["tenant_id"]) == tenant.id


def test_callback_state_mismatch_rejected(client, configure_oidc, rsa_keypair):
    _, jwk = rsa_keypair
    with _mock_idp(jwk):
        client.get("/api/v1/auth/oidc/login", follow_redirects=False)

    r = client.get(
        "/api/v1/auth/oidc/callback?code=abc&state=BOGUS",
        follow_redirects=False,
    )
    assert r.status_code == 401
    assert r.json()["code"] == "unauthorized"


def test_logout_clears_session(client, make_tenant, make_user, login_as):
    t = make_tenant()
    u = make_user(t.id)
    login_as(u)
    assert client.get("/api/v1/me").status_code == 200

    r = client.post("/api/v1/auth/logout")
    assert r.status_code == 204
    # cookie cleared
    client.cookies.clear()
    assert client.get("/api/v1/me").status_code == 401
