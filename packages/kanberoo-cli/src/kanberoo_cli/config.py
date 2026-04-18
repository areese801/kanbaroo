"""
Config loader for the Kanberoo CLI.

Every command that talks to the server needs three things: an
``api_url``, a ``token``, and (for ``kb backup``) a ``database_url``.
All three are written to ``$KANBEROO_CONFIG_DIR/config.toml`` by
``kb init``. This module provides a single :func:`load_config` entry
point that reads that file, applies environment-variable overrides,
and surfaces a dataclass the command handlers can consume without
re-parsing TOML every time.

If the config file is missing the loader raises
:class:`ConfigNotFoundError`, which the CLI translates into a clean
Rich-rendered message pointing the user at ``kb init``. We deliberately
do not fall back to a partial config: if ``config.toml`` does not exist
the user has not finished setup and we should say so loudly.
"""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """
    Base class for CLI configuration failures.
    """


class ConfigNotFoundError(ConfigError):
    """
    Raised when the expected ``config.toml`` does not exist.

    The CLI translates this into a 1-exit with a Rich-rendered hint
    pointing the user at ``kb init``.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(f"Kanberoo config not found at {path}")
        self.path = path


class ConfigMalformedError(ConfigError):
    """
    Raised when ``config.toml`` is present but missing a required key or
    contains a value of the wrong type.
    """


@dataclass(frozen=True)
class CliConfig:
    """
    In-memory representation of the CLI's on-disk configuration.

    ``database_url`` is needed by ``kb backup`` to locate the raw
    SQLite file for a local snapshot; every other command only needs
    ``api_url`` and ``token``.
    """

    api_url: str
    token: str
    database_url: str
    config_path: Path


def default_config_dir() -> Path:
    """
    Resolve the config directory from ``$KANBEROO_CONFIG_DIR`` or fall
    back to ``$HOME/.kanberoo``.

    Mirrors the helper inside ``kb init`` so both commands share the
    same resolution logic without leaking the init module's internals.
    """
    override = os.environ.get("KANBEROO_CONFIG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".kanberoo"


def default_config_path() -> Path:
    """
    Resolve the canonical ``config.toml`` path.
    """
    return default_config_dir() / "config.toml"


def load_config(path: Path | None = None) -> CliConfig:
    """
    Read ``config.toml`` and return a :class:`CliConfig`.

    ``$KANBEROO_API_URL``, ``$KANBEROO_TOKEN``, and
    ``$KANBEROO_DATABASE_URL`` each override the matching TOML field
    when set; this lets the test suite and CI pipelines drive the CLI
    without touching a user's config.

    Raises :class:`ConfigNotFoundError` when the file is absent and
    :class:`ConfigMalformedError` when it is present but incomplete.
    """
    resolved_path = path or default_config_path()
    if not resolved_path.exists():
        raise ConfigNotFoundError(resolved_path)

    with resolved_path.open("rb") as fh:
        raw = tomllib.load(fh)

    api_url = os.environ.get("KANBEROO_API_URL") or raw.get("api_url")
    token = os.environ.get("KANBEROO_TOKEN") or raw.get("token")
    database_url = os.environ.get("KANBEROO_DATABASE_URL") or raw.get("database_url")

    missing: list[str] = []
    if not isinstance(api_url, str) or not api_url:
        missing.append("api_url")
    if not isinstance(token, str) or not token:
        missing.append("token")
    if not isinstance(database_url, str) or not database_url:
        missing.append("database_url")
    if missing:
        raise ConfigMalformedError(
            f"config.toml at {resolved_path} is missing: {', '.join(missing)}"
        )

    assert isinstance(api_url, str)
    assert isinstance(token, str)
    assert isinstance(database_url, str)
    return CliConfig(
        api_url=api_url,
        token=token,
        database_url=database_url,
        config_path=resolved_path,
    )
