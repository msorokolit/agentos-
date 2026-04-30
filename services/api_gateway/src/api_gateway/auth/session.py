"""Session cookie management.

We use a small signed-and-encrypted JSON blob (HS256 JWT) carrying just
enough state to re-load the Principal on every request without hitting
the IdP. DB lookup happens once per request to refresh role + workspace
membership.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from agenticos_shared.errors import UnauthorizedError
from jose import jwt
from jose.exceptions import JWTError

SESSION_AUDIENCE = "agenticos.session"


@dataclass
class SessionPayload:
    """Minimal session state stored in the cookie."""

    user_id: UUID
    tenant_id: UUID
    email: str
    display_name: str | None
    issued_at: int
    expires_at: int

    def is_expired(self, now: int | None = None) -> bool:
        return (now or int(time.time())) >= self.expires_at


def encode_session(payload: SessionPayload, *, secret: str) -> str:
    body: dict[str, Any] = {
        "sub": str(payload.user_id),
        "tenant_id": str(payload.tenant_id),
        "email": payload.email,
        "name": payload.display_name,
        "iat": payload.issued_at,
        "exp": payload.expires_at,
        "aud": SESSION_AUDIENCE,
        "iss": "agenticos-gateway",
    }
    return jwt.encode(body, secret, algorithm="HS256")


def decode_session(token: str, *, secret: str) -> SessionPayload:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=SESSION_AUDIENCE,
            issuer="agenticos-gateway",
        )
    except JWTError as exc:
        raise UnauthorizedError("invalid session cookie") from exc

    return SessionPayload(
        user_id=UUID(claims["sub"]),
        tenant_id=UUID(claims["tenant_id"]),
        email=claims["email"],
        display_name=claims.get("name"),
        issued_at=int(claims["iat"]),
        expires_at=int(claims["exp"]),
    )
