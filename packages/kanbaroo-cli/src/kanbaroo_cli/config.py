"""
Config loader for the Kanbaroo CLI.

Every command that talks to the server needs three things: an
``api_url``, a ``token``, and (for ``kb backup``) a ``database_url``.
All three are written to ``$KANBAROO_CONFIG_DIR/config.toml`` by
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
from typing import Any


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
        super().__init__(f"Kanbaroo config not found at {path}")
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
    ``api_url`` and ``token``. The field is typed ``str | None`` so the
    API-only loader can skip the database-url validation and still
    return a usable config (the HTTP-probe path in ``kb server start
    --wait`` does not care where the database lives). Commands that
    actually need the URL route through :func:`load_config`, which keeps
    it mandatory.

    ``default_workspace`` is the optional workspace key most
    mutating/listing commands fall back to when neither ``--workspace``
    nor ``$KANBAROO_WORKSPACE`` is set. It is written by
    ``kb workspace use`` and may be absent in older configs.
    """

    api_url: str
    token: str
    database_url: str | None
    config_path: Path
    default_workspace: str | None = None


def default_config_dir() -> Path:
    """
    Resolve the config directory from ``$KANBAROO_CONFIG_DIR`` or fall
    back to ``$HOME/.kanbaroo``.

    Mirrors the helper inside ``kb init`` so both commands share the
    same resolution logic without leaking the init module's internals.
    """
    override = os.environ.get("KANBAROO_CONFIG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".kanbaroo"


def default_config_path() -> Path:
    """
    Resolve the canonical ``config.toml`` path.
    """
    return default_config_dir() / "config.toml"


def load_config(
    path: Path | None = None,
    *,
    require_database_url: bool = True,
) -> CliConfig:
    """
    Read ``config.toml`` and return a :class:`CliConfig`.

    ``$KANBAROO_API_URL``, ``$KANBAROO_TOKEN``, and
    ``$KANBAROO_DATABASE_URL`` each override the matching TOML field
    when set; this lets the test suite and CI pipelines drive the CLI
    without touching a user's config.

    ``api_url`` and ``token`` are always required.
    ``require_database_url`` defaults to ``True``; pass ``False`` via
    :func:`load_config_api_only` for commands that only hit the HTTP
    API and never open the database directly (e.g.
    ``kb server start --wait``).

    TODO: broader CLI split needed between API-client commands (that
    speak HTTP) and direct-DB-client commands (``kb backup``) so the
    required-field set is implicit from the command rather than
    manually wired per call site. Track alongside the API-client vs
    direct-DB-client modes note in TODO.md.

    Raises :class:`ConfigNotFoundError` when the file is absent and
    :class:`ConfigMalformedError` when it is present but incomplete.
    """
    resolved_path = path or default_config_path()
    if not resolved_path.exists():
        raise ConfigNotFoundError(resolved_path)

    with resolved_path.open("rb") as fh:
        raw = tomllib.load(fh)

    api_url = os.environ.get("KANBAROO_API_URL") or raw.get("api_url")
    token = os.environ.get("KANBAROO_TOKEN") or raw.get("token")
    database_url_raw = os.environ.get("KANBAROO_DATABASE_URL") or raw.get(
        "database_url"
    )
    default_workspace_raw = raw.get("default_workspace")

    missing: list[str] = []
    if not isinstance(api_url, str) or not api_url:
        missing.append("api_url")
    if not isinstance(token, str) or not token:
        missing.append("token")
    if require_database_url and (
        not isinstance(database_url_raw, str) or not database_url_raw
    ):
        missing.append("database_url")
    if missing:
        raise ConfigMalformedError(
            f"config.toml at {resolved_path} is missing: {', '.join(missing)}"
        )
    if default_workspace_raw is not None and (
        not isinstance(default_workspace_raw, str) or not default_workspace_raw
    ):
        raise ConfigMalformedError(
            f"config.toml at {resolved_path} has an invalid default_workspace"
        )

    assert isinstance(api_url, str)
    assert isinstance(token, str)
    database_url: str | None = (
        database_url_raw
        if isinstance(database_url_raw, str) and database_url_raw
        else None
    )
    default_workspace: str | None = (
        default_workspace_raw if isinstance(default_workspace_raw, str) else None
    )
    return CliConfig(
        api_url=api_url,
        token=token,
        database_url=database_url,
        config_path=resolved_path,
        default_workspace=default_workspace,
    )


def load_config_api_only(path: Path | None = None) -> CliConfig:
    """
    Like :func:`load_config` but does not require ``database_url``.

    Used by commands that only need to talk to the running HTTP API
    and never read the local database. ``database_url`` may be absent
    from ``config.toml`` entirely; in that case the returned
    ``CliConfig.database_url`` is ``None``.
    """
    return load_config(path, require_database_url=False)


def _escape_toml(value: str) -> str:
    """
    Escape a string value for a TOML basic string literal.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _render_config_toml(values: dict[str, Any]) -> str:
    """
    Render a minimal ``config.toml`` from a mapping of string scalars.

    ``None`` values are omitted. Key order is preserved so rewrites do
    not reshuffle the file unnecessarily.
    """
    lines: list[str] = []
    for key, value in values.items():
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError(f"config value for {key!r} must be str, got {type(value)}")
        lines.append(f'{key} = "{_escape_toml(value)}"')
    return "\n".join(lines) + "\n"


def write_default_workspace(path: Path, workspace_key: str | None) -> None:
    """
    Rewrite ``config.toml`` at ``path`` to set ``default_workspace`` to
    ``workspace_key`` (or remove it when ``None``).

    Preserves every other key present in the file. Used by
    ``kb workspace use``.
    """
    if not path.exists():
        raise ConfigNotFoundError(path)
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    if workspace_key is None:
        raw.pop("default_workspace", None)
    else:
        raw["default_workspace"] = workspace_key
    path.write_text(_render_config_toml(raw), encoding="utf-8")
