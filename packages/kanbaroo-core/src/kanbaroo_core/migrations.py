"""
Locate and run the Alembic migrations shipped with kanbaroo-core.

The CLI's ``kb init`` command runs migrations programmatically rather
than shelling out to ``alembic``, so it needs a stable handle on the
``alembic/`` directory regardless of how the package was installed
(editable workspace checkout vs. built wheel). This module encapsulates
that lookup and exposes a small :func:`upgrade_to_head` helper that
wires the right ``script_location`` and URL into an Alembic
:class:`~alembic.config.Config`.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

import kanbaroo_core


def alembic_script_location() -> str:
    """
    Return the filesystem path to the Alembic ``script_location``.

    Tries the wheel-install layout first (``alembic/`` shipped inside
    the package via hatch force-include) and then falls back to the
    source-checkout layout (``alembic/`` sibling to ``src/`` in the
    package root, which is what editable installs see).
    """
    pkg_dir = Path(kanbaroo_core.__file__).resolve().parent
    wheel_location = pkg_dir / "alembic"
    if wheel_location.is_dir():
        return str(wheel_location)

    source_location = pkg_dir.parent.parent / "alembic"
    if source_location.is_dir():
        return str(source_location)

    raise FileNotFoundError(
        "Could not locate the kanbaroo-core alembic directory. Checked "
        f"{wheel_location} and {source_location}."
    )


def build_alembic_config(database_url: str) -> Config:
    """
    Build an Alembic :class:`~alembic.config.Config` pointed at the
    bundled migration scripts and the given database URL.

    The returned config is fully in-memory and does not depend on the
    on-disk ``alembic.ini``; the CLI uses this so it works regardless
    of the current working directory.
    """
    cfg = Config()
    cfg.set_main_option("script_location", alembic_script_location())
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def upgrade_to_head(database_url: str) -> None:
    """
    Apply every Alembic migration up to ``head`` against the given URL.

    Safe to call against a fresh, empty database or one that is already
    at head; in the latter case Alembic is a no-op.
    """
    command.upgrade(build_alembic_config(database_url), "head")
