"""
Alembic environment for the Kanberoo core schema.

Reads ``sqlalchemy.url`` from ``alembic.ini`` by default; the env var
``KANBEROO_DATABASE_URL`` overrides it when set. Importing
:mod:`kanberoo_core.models` registers every table on
``Base.metadata``, which is what Alembic compares against.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from kanberoo_core import models  # noqa: F401  (registers tables on Base.metadata)
from kanberoo_core.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_url_override = os.environ.get("KANBEROO_DATABASE_URL")
if _url_override:
    config.set_main_option("sqlalchemy.url", _url_override)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations without an active DBAPI connection.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations with an active DBAPI connection.
    """
    section = config.get_section(config.config_ini_section, {}) or {}
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
