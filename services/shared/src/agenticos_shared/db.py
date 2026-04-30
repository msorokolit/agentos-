"""SQLAlchemy engine + session helpers.

Provides a single :func:`get_engine` factory and a ``SessionLocal``
contextmanager. Most application code should depend on the higher-level
``with session_scope() as session:`` pattern below.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Initialise (or replace) the process-wide SQLAlchemy engine."""

    global _engine, _SessionLocal
    _engine = create_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        future=True,
    )
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Engine not initialised; call init_engine() first.")
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    if _SessionLocal is None:
        raise RuntimeError("SessionLocal not initialised; call init_engine() first.")
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a transactional session scope.

    Commits on success, rolls back on exception, always closes.
    """

    sm = get_sessionmaker()
    session = sm()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
