"""api-gateway DB session dependency."""

from __future__ import annotations

from collections.abc import Iterator

from agenticos_shared.db import get_sessionmaker, init_engine
from sqlalchemy.orm import Session

from .settings import get_settings


def init_db() -> None:
    """Initialise the global SQLAlchemy engine for this process."""

    s = get_settings()
    init_engine(s.database_url, echo=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yields a SQLAlchemy session, committed at end."""

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
