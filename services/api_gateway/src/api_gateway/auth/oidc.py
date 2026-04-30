"""Tiny, explicit OIDC client.

We do **not** depend on Authlib's full OAuth client — we only need three
calls (discover, exchange code, fetch JWKS) and want them easily mockable
with ``respx`` in unit tests.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx
from agenticos_shared.errors import UnauthorizedError
from jose import jwt
from jose.exceptions import JWKError, JWTError


# ---------------------------------------------------------------------------
# Discovery + JWKS cache
# ---------------------------------------------------------------------------
@dataclass
class OIDCMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class _CachedJWKS:
    keys: list[dict[str, Any]]
    fetched_at: float


_DISCOVERY_CACHE: dict[str, tuple[OIDCMetadata, float]] = {}
_JWKS_CACHE: dict[str, _CachedJWKS] = {}
_DISCOVERY_TTL = 600.0
_JWKS_TTL = 600.0


async def discover(issuer: str, *, http: httpx.AsyncClient | None = None) -> OIDCMetadata:
    """Fetch the OIDC discovery document, cached for 10 minutes."""

    now = time.monotonic()
    cached = _DISCOVERY_CACHE.get(issuer)
    if cached and (now - cached[1]) < _DISCOVERY_TTL:
        return cached[0]

    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    client = http or httpx.AsyncClient(timeout=5.0)
    own = http is None
    try:
        r = await client.get(url)
        r.raise_for_status()
        raw = r.json()
    finally:
        if own:
            await client.aclose()

    md = OIDCMetadata(
        issuer=raw["issuer"],
        authorization_endpoint=raw["authorization_endpoint"],
        token_endpoint=raw["token_endpoint"],
        jwks_uri=raw["jwks_uri"],
        end_session_endpoint=raw.get("end_session_endpoint"),
        raw=raw,
    )
    _DISCOVERY_CACHE[issuer] = (md, now)
    return md


async def fetch_jwks(
    jwks_uri: str, *, http: httpx.AsyncClient | None = None
) -> list[dict[str, Any]]:
    """Fetch + cache the JWKS for an issuer."""

    now = time.monotonic()
    cached = _JWKS_CACHE.get(jwks_uri)
    if cached and (now - cached.fetched_at) < _JWKS_TTL:
        return cached.keys

    client = http or httpx.AsyncClient(timeout=5.0)
    own = http is None
    try:
        r = await client.get(jwks_uri)
        r.raise_for_status()
        raw = r.json()
    finally:
        if own:
            await client.aclose()

    keys = list(raw.get("keys", []))
    _JWKS_CACHE[jwks_uri] = _CachedJWKS(keys=keys, fetched_at=now)
    return keys


def _clear_caches() -> None:
    """Test helper — wipe the in-process discovery + JWKS caches."""

    _DISCOVERY_CACHE.clear()
    _JWKS_CACHE.clear()


# ---------------------------------------------------------------------------
# Auth-code flow
# ---------------------------------------------------------------------------
def build_login_url(
    md: OIDCMetadata,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    scopes: tuple[str, ...] = ("openid", "profile", "email"),
) -> str:
    qs = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "nonce": nonce,
        }
    )
    return f"{md.authorization_endpoint}?{qs}"


async def exchange_code(
    md: OIDCMetadata,
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    http: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens."""

    client = http or httpx.AsyncClient(timeout=10.0)
    own = http is None
    try:
        r = await client.post(
            md.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Accept": "application/json"},
        )
        if r.status_code >= 400:
            raise UnauthorizedError(f"token exchange failed: {r.status_code} {r.text[:200]}")
        return r.json()
    finally:
        if own:
            await client.aclose()


# ---------------------------------------------------------------------------
# ID-token verification
# ---------------------------------------------------------------------------
@dataclass
class IDTokenClaims:
    sub: str
    email: str
    email_verified: bool
    name: str | None
    iss: str
    aud: str
    exp: int
    nonce: str | None
    raw: dict[str, Any]


async def verify_id_token(
    id_token: str,
    *,
    md: OIDCMetadata,
    audience: str,
    nonce: str | None = None,
    http: httpx.AsyncClient | None = None,
) -> IDTokenClaims:
    """Verify an ID token signature, issuer, audience, expiry, and nonce."""

    try:
        unverified_header = jwt.get_unverified_header(id_token)
    except JWTError as exc:
        raise UnauthorizedError(f"malformed id_token: {exc}") from exc

    kid = unverified_header.get("kid")
    keys = await fetch_jwks(md.jwks_uri, http=http)
    key = (
        next((k for k in keys if k.get("kid") == kid), None) if kid else (keys[0] if keys else None)
    )
    if key is None:
        raise UnauthorizedError("no matching JWK for id_token")

    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=[unverified_header.get("alg", "RS256")],
            audience=audience,
            issuer=md.issuer,
            options={"verify_at_hash": False},
        )
    except (JWTError, JWKError) as exc:
        raise UnauthorizedError(f"id_token verify failed: {exc}") from exc

    if nonce is not None and claims.get("nonce") != nonce:
        raise UnauthorizedError("nonce mismatch")

    return IDTokenClaims(
        sub=claims["sub"],
        email=claims.get("email") or claims.get("preferred_username") or "",
        email_verified=bool(claims.get("email_verified", False)),
        name=claims.get("name") or claims.get("preferred_username"),
        iss=claims["iss"],
        aud=claims["aud"] if isinstance(claims["aud"], str) else claims["aud"][0],
        exp=int(claims["exp"]),
        nonce=claims.get("nonce"),
        raw=claims,
    )


def random_token(n_bytes: int = 24) -> str:
    """Generate a URL-safe random token used for ``state`` and ``nonce``."""

    return secrets.token_urlsafe(n_bytes)
