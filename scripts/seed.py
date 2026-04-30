"""Seed dev data — idempotent.

Creates:
- ``acme`` tenant
- ``default`` workspace under acme
- ``alice@agenticos.local`` as superuser, owner of default
- ``bob@agenticos.local`` as builder of default

Usage:
    docker compose run --rm api-gateway python -m scripts.seed
or
    DATABASE_URL=... python -m scripts.seed
"""

from __future__ import annotations

import sys
from uuid import uuid4

from agenticos_shared.db import init_engine, session_scope
from agenticos_shared.models import Tenant, User, Workspace, WorkspaceMember
from agenticos_shared.settings import get_settings
from sqlalchemy import select


def _get_or_create_tenant(db, slug: str, name: str) -> Tenant:
    t = db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none()
    if t is None:
        t = Tenant(id=uuid4(), slug=slug, name=name)
        db.add(t)
        db.flush()
        print(f"  + tenant: {slug}")
    else:
        print(f"  = tenant: {slug}")
    return t


def _get_or_create_workspace(db, tenant_id, slug: str, name: str) -> Workspace:
    w = db.execute(
        select(Workspace).where(Workspace.tenant_id == tenant_id, Workspace.slug == slug)
    ).scalar_one_or_none()
    if w is None:
        w = Workspace(id=uuid4(), tenant_id=tenant_id, slug=slug, name=name)
        db.add(w)
        db.flush()
        print(f"  + workspace: {slug}")
    else:
        print(f"  = workspace: {slug}")
    return w


def _get_or_create_user(
    db, tenant_id, email: str, display_name: str, *, is_superuser: bool = False
) -> User:
    u = db.execute(
        select(User).where(User.tenant_id == tenant_id, User.email == email)
    ).scalar_one_or_none()
    if u is None:
        u = User(
            id=uuid4(),
            tenant_id=tenant_id,
            email=email,
            display_name=display_name,
            is_superuser=is_superuser,
        )
        db.add(u)
        db.flush()
        print(f"  + user: {email}{' (superuser)' if is_superuser else ''}")
    else:
        if is_superuser and not u.is_superuser:
            u.is_superuser = True
        print(f"  = user: {email}")
    return u


def _ensure_member(db, workspace_id, user_id, role: str) -> None:
    m = db.get(WorkspaceMember, (workspace_id, user_id))
    if m is None:
        db.add(WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role))
        print(f"    + member role={role}")
    elif m.role != role:
        m.role = role
        print(f"    ~ role -> {role}")


def main(*, init: bool = True) -> int:
    """Seed the database. Pass ``init=False`` if the engine is already set up."""

    if init:
        settings = get_settings()
        print(f"Seeding into {settings.database_url}")
        init_engine(settings.database_url)

    with session_scope() as db:
        acme = _get_or_create_tenant(db, "acme", "Acme")
        default_ws = _get_or_create_workspace(db, acme.id, "default", "Default")

        alice = _get_or_create_user(
            db, acme.id, "alice@agenticos.local", "Alice", is_superuser=True
        )
        bob = _get_or_create_user(db, acme.id, "bob@agenticos.local", "Bob")
        _ensure_member(db, default_ws.id, alice.id, "owner")
        _ensure_member(db, default_ws.id, bob.id, "builder")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
