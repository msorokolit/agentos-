"""RBAC permission matrix."""

from __future__ import annotations

from uuid import uuid4

import pytest
from agenticos_shared.auth import Principal
from agenticos_shared.errors import ForbiddenError
from api_gateway.auth.deps import (
    PERMISSIONS,
    ROLE_RANK,
    require_role,
)


def _principal(roles: list[str]) -> Principal:
    return Principal(
        user_id=uuid4(),
        tenant_id=uuid4(),
        email="x@y.z",
        roles=roles,
    )


@pytest.mark.parametrize(
    "min_role,roles,allowed",
    [
        ("viewer", ["viewer"], True),
        ("member", ["viewer"], False),
        ("admin", ["builder"], False),
        ("admin", ["admin"], True),
        ("owner", ["admin"], False),
        ("owner", ["owner"], True),
        ("admin", ["superuser"], True),  # superuser bypasses
    ],
)
def test_require_role(min_role, roles, allowed) -> None:
    dep = require_role(min_role)
    p = _principal(roles)
    if allowed:
        assert dep(principal=p) is p
    else:
        with pytest.raises(ForbiddenError):
            dep(principal=p)


def test_role_rank_ordering() -> None:
    assert (
        ROLE_RANK["viewer"]
        < ROLE_RANK["member"]
        < ROLE_RANK["builder"]
        < ROLE_RANK["admin"]
        < ROLE_RANK["owner"]
    )


def test_permission_matrix_sane() -> None:
    # owner can do everything
    owner = ROLE_RANK["owner"]
    for _, needed in PERMISSIONS.items():
        assert owner >= needed
    # viewer cannot do writes
    viewer = ROLE_RANK["viewer"]
    assert viewer < PERMISSIONS["agent:write"]
    assert viewer < PERMISSIONS["workspace:write"]
