"""
Request-scoped SQLAlchemy session dependency.

The engine is created once at application startup and stored on
``app.state``. Every request opens a session, runs the endpoint, and
either commits on success or rolls back on exception. This is the
single place in the stack where transaction boundaries are owned:
service functions flush but never commit.
"""

from collections.abc import Iterator
from typing import Any

from fastapi import Request
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from kanbaroo_core.db import engine_for_url


def configure_engine(app_state: Any, database_url: str, **engine_kwargs: Any) -> Engine:
    """
    Build a SQLAlchemy engine and stash it (plus a ``sessionmaker``) on
    the given FastAPI ``app.state`` container.

    Keeping engine construction here means tests can wire a
    ``StaticPool`` engine onto an app with exactly the same shape the
    production path uses.
    """
    engine = engine_for_url(database_url, **engine_kwargs)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app_state.engine = engine
    app_state.session_factory = factory
    return engine


def get_session(request: Request) -> Iterator[Session]:
    """
    FastAPI dependency that yields a session per request.

    The session commits on successful return, rolls back on any raised
    exception (including service-layer domain errors like
    :class:`kanbaroo_core.services.exceptions.VersionConflictError` so
    partial writes never hit the database), and always closes in the
    ``finally`` block.
    """
    factory: sessionmaker[Session] = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
