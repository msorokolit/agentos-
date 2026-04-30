"""SessionPayload encode/decode."""

from __future__ import annotations

import time
from uuid import uuid4

import pytest
from agenticos_shared.errors import UnauthorizedError
from api_gateway.auth.session import SessionPayload, decode_session, encode_session

SECRET = "test-secret-32-bytes-or-more!!!"


def _payload(ttl: int = 3600) -> SessionPayload:
    now = int(time.time())
    return SessionPayload(
        user_id=uuid4(),
        tenant_id=uuid4(),
        email="alice@example.com",
        display_name="Alice",
        issued_at=now,
        expires_at=now + ttl,
    )


def test_session_roundtrip() -> None:
    p = _payload()
    tok = encode_session(p, secret=SECRET)
    out = decode_session(tok, secret=SECRET)
    assert out.user_id == p.user_id
    assert out.tenant_id == p.tenant_id
    assert out.email == p.email
    assert out.display_name == "Alice"


def test_session_invalid_secret_rejected() -> None:
    tok = encode_session(_payload(), secret=SECRET)
    with pytest.raises(UnauthorizedError):
        decode_session(tok, secret="other-secret-32-bytes-or-more!!")


def test_session_expiry_flag() -> None:
    p = _payload(ttl=-10)
    assert p.is_expired() is True
    fresh = _payload()
    assert fresh.is_expired() is False
