"""FastAPI dependencies for authentication and authorisation."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from agenticos_shared.auth import Principal
from agenticos_shared.errors import ForbiddenError, NotFoundError, UnauthorizedError
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..settings import Settings, get_settings
from .session import decode_session

# Avoid a circular import by referring to ORM models via fully-qualified path
# inside the function body.


def _principal_from_request(
    request: Request,
    db: Session,
    settings: Settings,
    *,
    required: bool,
) -> Principal | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        # Allow ``Authorization: Bearer <session-cookie>`` for SDKs.
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1]
    if not token:
        if required:
            raise UnauthorizedError("not authenticated")
        return None

    payload = decode_session(token, secret=settings.secret_key)
    if payload.is_expired():
        raise UnauthorizedError("session expired")

    # Hydrate roles + workspace_ids from the DB on every request so role
    # changes take effect immediately.
    from agenticos_shared.models import User, WorkspaceMember  # local import

    user = db.get(User, payload.user_id)
    if user is None:
        raise UnauthorizedError("user not found")

    rows = db.execute(
        select(WorkspaceMember.workspace_id, WorkspaceMember.role).where(
            WorkspaceMember.user_id == user.id
        )
    ).all()
    roles = sorted({r for _, r in rows})
    workspace_ids = [w for w, _ in rows]
    if user.is_superuser:
        roles = sorted({*roles, "superuser"})

    return Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        display_name=user.display_name,
        roles=roles,
        workspace_ids=workspace_ids,
        request_id=request.headers.get("x-request-id"),
    )


def current_principal(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Principal:
    """FastAPI dependency: required Principal."""

    p = _principal_from_request(request, db, settings, required=True)
    assert p is not None
    return p


def optional_principal(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Principal | None:
    """FastAPI dependency: Principal if logged in, else None."""

    return _principal_from_request(request, db, settings, required=False)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
ROLE_RANK = {
    "viewer": 0,
    "member": 1,
    "builder": 2,
    "admin": 3,
    "owner": 4,
}

PERMISSIONS: dict[str, int] = {
    # workspace mgmt
    "workspace:read": ROLE_RANK["viewer"],
    "workspace:write": ROLE_RANK["admin"],
    "workspace:delete": ROLE_RANK["owner"],
    # members mgmt
    "member:read": ROLE_RANK["member"],
    "member:write": ROLE_RANK["admin"],
    # agents
    "agent:read": ROLE_RANK["viewer"],
    "agent:write": ROLE_RANK["builder"],
    "agent:delete": ROLE_RANK["admin"],
    # tools
    "tool:read": ROLE_RANK["member"],
    "tool:write": ROLE_RANK["admin"],
    # documents
    "document:read": ROLE_RANK["viewer"],
    "document:write": ROLE_RANK["builder"],
    # admin
    "admin:read": ROLE_RANK["admin"],
    "admin:write": ROLE_RANK["owner"],
}


def _highest_rank(roles: list[str]) -> int:
    return max((ROLE_RANK.get(r, -1) for r in roles), default=-1)


def require_admin(
    principal: Principal = Depends(current_principal),
) -> Principal:
    """Require the caller to be a tenant-level admin or superuser."""

    if "superuser" in principal.roles or "owner" in principal.roles or "admin" in principal.roles:
        return principal
    raise ForbiddenError("admin role required")


def require_role(min_role: str) -> Callable[..., Principal]:
    """Caller must have at least ``min_role`` in *some* workspace."""

    min_rank = ROLE_RANK[min_role]

    def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if "superuser" in principal.roles:
            return principal
        if _highest_rank(principal.roles) >= min_rank:
            return principal
        raise ForbiddenError(f"requires role >= {min_role}")

    return _dep


def require_workspace_role(perm: str) -> Callable[..., tuple[Principal, UUID]]:
    """Require the caller's role *in the path workspace* to grant ``perm``.

    The route MUST take a path parameter named ``workspace_id``.
    """

    if perm not in PERMISSIONS:
        raise KeyError(f"unknown permission: {perm}")
    needed = PERMISSIONS[perm]

    def _dep(
        workspace_id: UUID,
        principal: Principal = Depends(current_principal),
        db: Session = Depends(get_db),
    ) -> tuple[Principal, UUID]:
        if "superuser" in principal.roles:
            return principal, workspace_id

        from agenticos_shared.models import Workspace, WorkspaceMember  # local import

        ws = db.get(Workspace, workspace_id)
        if ws is None or ws.tenant_id != principal.tenant_id:
            raise NotFoundError("workspace not found")

        row = db.execute(
            select(WorkspaceMember.role).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == principal.user_id,
            )
        ).scalar_one_or_none()
        if row is None:
            raise ForbiddenError("not a workspace member")

        if ROLE_RANK.get(row, -1) < needed:
            raise ForbiddenError(f"role '{row}' insufficient for '{perm}'")
        return principal, workspace_id

    return _dep
