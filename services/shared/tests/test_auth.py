"""Internal JWT mint/verify."""

from __future__ import annotations

from uuid import uuid4

import pytest
from agenticos_shared.auth import (
    Principal,
    make_internal_token,
    verify_internal_token,
)
from agenticos_shared.errors import UnauthorizedError

SECRET = "test-secret-32-bytes-or-more!!!"


def _principal() -> Principal:
    return Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        email="alice@example.com",
        roles=["admin"],
        workspace_ids=[uuid4()],
        request_id="req-1",
    )


def test_internal_token_roundtrip() -> None:
    p = _principal()
    tok = make_internal_token(principal=p, secret=SECRET, audience="agent-runtime")
    out = verify_internal_token(tok, secret=SECRET, audience="agent-runtime")
    assert out.user_id == p.user_id
    assert out.tenant_id == p.tenant_id
    assert out.email == p.email
    assert out.roles == p.roles
    assert out.workspace_ids == p.workspace_ids
    assert out.request_id == p.request_id


def test_internal_token_wrong_audience_rejected() -> None:
    tok = make_internal_token(principal=_principal(), secret=SECRET, audience="a")
    with pytest.raises(UnauthorizedError):
        verify_internal_token(tok, secret=SECRET, audience="b")


def test_internal_token_wrong_secret_rejected() -> None:
    tok = make_internal_token(principal=_principal(), secret=SECRET, audience="a")
    with pytest.raises(UnauthorizedError):
        verify_internal_token(tok, secret="other-secret-32-bytes-or-more!!!", audience="a")


def test_principal_admin_flag() -> None:
    p = _principal()
    assert p.is_admin is True
    p2 = p.model_copy(update={"roles": ["member"]})
    assert p2.is_admin is False
