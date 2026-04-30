"""Authentication primitives shared across services.

The actual OIDC handshake lives in ``api_gateway``; here we expose the
``Principal`` model and a small JWT verifier that can be reused inside
service-to-service calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from jose import JWTError, jwt
from pydantic import BaseModel, Field

from .errors import UnauthorizedError


class Principal(BaseModel):
    """Authenticated caller as known to all services.

    Constructed by ``api_gateway`` from a verified OIDC token, then
    forwarded internally either via JWT or via signed headers.
    """

    user_id: UUID
    tenant_id: UUID
    email: str
    display_name: str | None = None
    roles: list[str] = Field(default_factory=list)
    workspace_ids: list[UUID] = Field(default_factory=list)
    is_service: bool = False
    request_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles or "owner" in self.roles


class ServicePrincipal(Principal):
    """Convenience subclass for service-to-service calls."""

    is_service: bool = True


def make_internal_token(
    *,
    principal: Principal,
    secret: str,
    audience: str,
    ttl_seconds: int = 60,
) -> str:
    """Mint a short-lived HS256 token for service-to-service calls."""

    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "sub": str(principal.user_id),
        "tenant_id": str(principal.tenant_id),
        "email": principal.email,
        "roles": principal.roles,
        "workspace_ids": [str(w) for w in principal.workspace_ids],
        "is_service": principal.is_service,
        "request_id": principal.request_id,
        "aud": audience,
        "iss": "agenticos-internal",
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + ttl_seconds,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_internal_token(token: str, *, secret: str, audience: str) -> Principal:
    """Verify an internal HS256 token and return the embedded Principal."""

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=audience,
            issuer="agenticos-internal",
        )
    except JWTError as exc:  # pragma: no cover - defensive
        raise UnauthorizedError("invalid internal token") from exc

    return Principal(
        user_id=UUID(claims["sub"]),
        tenant_id=UUID(claims["tenant_id"]),
        email=claims["email"],
        roles=list(claims.get("roles", [])),
        workspace_ids=[UUID(w) for w in claims.get("workspace_ids", [])],
        is_service=bool(claims.get("is_service", False)),
        request_id=claims.get("request_id"),
    )
