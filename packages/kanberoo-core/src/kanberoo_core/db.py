"""
Declarative base, ID generation, and SQLite engine helpers.

Models live in :mod:`kanberoo_core.models` and inherit from :class:`Base`
defined here. Importing this module does not pull in any models; importing
:mod:`kanberoo_core.models` does.

The ``engine_for_url`` helper standardises engine creation so SQLite always
has foreign-key enforcement turned on (off by default in the SQLite client
library) and so the engine is consistent between application code, tests,
and Alembic migrations.
"""

from typing import Any

import uuid_utils
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Declarative base for all Kanberoo ORM models.
    """


def new_id() -> str:
    """
    Return a fresh primary-key value.

    Kanberoo uses UUID v7 for all primary keys (see ``docs/spec.md`` section
    3.4): they are time-sortable, which yields good insert locality and
    makes the audit log naturally chronological. Stored as TEXT in both
    SQLite and Postgres for portability.
    """
    return str(uuid_utils.uuid7())


def engine_for_url(url: str, **kwargs: Any) -> Engine:
    """
    Create a SQLAlchemy engine with sensible defaults for Kanberoo.

    For SQLite URLs this attaches a ``connect`` listener that enables
    ``PRAGMA foreign_keys=ON`` on every new connection. Without this, FK
    constraints declared in the schema are silently ignored. Postgres
    enforces FKs unconditionally so no listener is attached there.
    """
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        _attach_sqlite_pragmas(engine)
    return engine


def _attach_sqlite_pragmas(engine: Engine) -> None:
    """
    Attach a SQLite-only ``connect`` event listener that enables foreign
    key enforcement on every new connection.
    """

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
