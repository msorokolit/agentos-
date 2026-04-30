"""Smoke test for scripts/seed.py — must be idempotent."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from agenticos_shared.models import Tenant, User, Workspace, WorkspaceMember
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _add_repo_root_to_path():
    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def test_seed_idempotent(db, db_engine):
    # Re-bind the shared module so seed.main picks up our SQLite engine.
    from agenticos_shared import db as shared_db

    shared_db._engine = db_engine
    from sqlalchemy.orm import sessionmaker

    shared_db._SessionLocal = sessionmaker(
        bind=db_engine, autoflush=False, autocommit=False, future=True
    )

    from scripts import seed

    assert seed.main(init=False) == 0
    # Run a second time — should not duplicate.
    assert seed.main(init=False) == 0

    tenants = db.execute(select(Tenant)).scalars().all()
    assert len(tenants) == 1
    assert tenants[0].slug == "acme"

    users = db.execute(select(User)).scalars().all()
    emails = {u.email for u in users}
    assert emails == {"alice@agenticos.local", "bob@agenticos.local"}

    workspaces = db.execute(select(Workspace)).scalars().all()
    assert {w.slug for w in workspaces} == {"default"}

    members = db.execute(select(WorkspaceMember)).scalars().all()
    assert len(members) == 2
    role_by_email = {next(u.email for u in users if u.id == m.user_id): m.role for m in members}
    assert role_by_email == {"alice@agenticos.local": "owner", "bob@agenticos.local": "builder"}
