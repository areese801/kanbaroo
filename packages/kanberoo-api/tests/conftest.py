"""
Fixtures for the ``kanberoo-api`` integration tests.

Each test gets a fresh FastAPI app backed by an in-memory SQLite
database. The database is stood up via
:func:`kanberoo_core.migrations.upgrade_to_head` so tests exercise the
actual production migration path rather than a ``Base.metadata.create_all``
shortcut.

A human token is created up-front and exposed through the ``human_auth``
fixture so tests can make authenticated requests in one line.
"""

from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from kanberoo_api.app import create_app
from kanberoo_api.db import configure_engine
from kanberoo_core import ActorType, models  # noqa: F401 (registers tables)
from kanberoo_core.auth import create_token
from kanberoo_core.db import Base, engine_for_url


@pytest.fixture
def app() -> Iterator[FastAPI]:
    """
    Build a FastAPI app whose engine is bound to an in-memory SQLite
    database with the full schema applied.

    We override the app.state engine after :func:`create_app` runs
    because the factory resolves the URL at construction time; the
    override swaps in a ``StaticPool`` engine so every session in the
    test sees the same SQLite connection (required for ``:memory:``).
    """
    app = create_app(database_url="sqlite:///:memory:")
    engine = engine_for_url(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    app.state.engine = engine
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield app
    finally:
        engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """
    Yield a FastAPI ``TestClient`` bound to the per-test app.
    """
    with TestClient(app) as c:
        yield c


@pytest.fixture
def session(app: FastAPI) -> Iterator[Session]:
    """
    Yield a raw SQLAlchemy session against the same engine the API
    uses. Useful for asserting audit rows without going through the
    HTTP surface.
    """
    factory: sessionmaker[Session] = app.state.session_factory
    session = factory()
    try:
        yield session
    finally:
        session.close()


@dataclass
class HumanAuth:
    """
    Bundle of the first human token's plaintext and the standard auth
    headers tests need to send authenticated requests.
    """

    plaintext: str
    headers: dict[str, str]


@pytest.fixture
def human_auth(app: FastAPI) -> HumanAuth:
    """
    Create the first human token against the in-memory database and
    return the plaintext plus an ``Authorization`` header dict.
    """
    factory: sessionmaker[Session] = app.state.session_factory
    session = factory()
    try:
        _row, plaintext = create_token(
            session,
            actor_type=ActorType.HUMAN,
            actor_id="adam",
            name="personal",
        )
        session.commit()
    finally:
        session.close()
    return HumanAuth(
        plaintext=plaintext,
        headers={"Authorization": f"Bearer {plaintext}"},
    )


def configure_engine_from_url(app: FastAPI, url: str) -> None:
    """
    Test helper that rebinds an app's engine to a new URL.

    Kept here (rather than inlined) so any test that needs a fresh
    database mid-session uses the same wiring the primary ``app``
    fixture does.
    """
    if hasattr(app.state, "engine") and app.state.engine is not None:
        app.state.engine.dispose()
    configure_engine(app.state, url)
