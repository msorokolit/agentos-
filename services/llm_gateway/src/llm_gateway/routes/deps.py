"""Shared dependencies for llm-gateway routes."""

from __future__ import annotations

from collections.abc import Iterator

from agenticos_shared.db import get_sessionmaker
from sqlalchemy.orm import Session


def get_db() -> Iterator[Session]:
    sm = get_sessionmaker()
    db = sm()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
