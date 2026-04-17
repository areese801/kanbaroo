"""
Pytest fixtures for the kanberoo-core test suite.

Each test gets a fresh in-memory SQLite database with the full schema
created via :meth:`Base.metadata.create_all`. Using ``StaticPool`` keeps
all sessions on the same single SQLite connection, which is required for
``:memory:`` databases (a new connection would see an empty database).
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from kanberoo_core import models  # noqa: F401  (registers tables on Base.metadata)
from kanberoo_core.db import Base, engine_for_url


@pytest.fixture
def engine() -> Iterator[Engine]:
    """
    Yield a fresh in-memory SQLite engine with the full schema applied
    and SQLite foreign-key enforcement on.
    """
    eng = engine_for_url(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """
    Yield a Session bound to the in-memory database.
    """
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()
