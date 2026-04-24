"""
Config loader for the Kanbaroo TUI.

Reads ``$KANBAROO_CONFIG_DIR/config.toml`` (default
``~/.kanbaroo/config.toml``) and applies the same environment-variable
overrides the CLI supports. The TUI only needs ``api_url`` and
``token``; ``database_url`` is ignored if present.

The loader is intentionally a fresh copy of the CLI's
``kanbaroo_cli.config`` module rather than a re-export. Coupling two
sibling front ends through a shared import would pull every CLI
dependency into the TUI package and vice-versa; duplication at this
scale is the lesser evil.
"""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """
    Base class for TUI configuration failures.
    """


class ConfigNotFoundError(ConfigError):
    """
    Raised when the expected ``config.toml`` does not exist.

    The TUI translates this into a short message on stderr suggesting
    the user run ``kb init``.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(f"Kanbaroo config not found at {path}")
        self.path = path


class ConfigMalformedError(ConfigError):
    """
    Raised when ``config.toml`` is present but missing a required key
    or contains a value of the wrong type.
    """


@dataclass(frozen=True)
class TuiConfig:
    """
    In-memory representation of the TUI's on-disk configuration.

    Only ``api_url`` and ``token`` are load-bearing. ``config_path`` is
    kept around so error messages can point the user back to the file
    they need to edit.
    """

    api_url: str
    token: str
    config_path: Path


def default_config_dir() -> Path:
    """
    Resolve the config directory from ``$KANBAROO_CONFIG_DIR`` or fall
    back to ``$HOME/.kanbaroo``.
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


def load_config(path: Path | None = None) -> TuiConfig:
    """
    Read ``config.toml`` and return a :class:`TuiConfig`.

    ``$KANBAROO_API_URL`` and ``$KANBAROO_TOKEN`` each override the
    matching TOML field when set. A missing file raises
    :class:`ConfigNotFoundError`; a present-but-incomplete file raises
    :class:`ConfigMalformedError`.
    """
    resolved_path = path or default_config_path()
    if not resolved_path.exists():
        raise ConfigNotFoundError(resolved_path)

    with resolved_path.open("rb") as fh:
        raw = tomllib.load(fh)

    api_url = os.environ.get("KANBAROO_API_URL") or raw.get("api_url")
    token = os.environ.get("KANBAROO_TOKEN") or raw.get("token")

    missing: list[str] = []
    if not isinstance(api_url, str) or not api_url:
        missing.append("api_url")
    if not isinstance(token, str) or not token:
        missing.append("token")
    if missing:
        raise ConfigMalformedError(
            f"config.toml at {resolved_path} is missing: {', '.join(missing)}"
        )

    assert isinstance(api_url, str)
    assert isinstance(token, str)
    return TuiConfig(
        api_url=api_url,
        token=token,
        config_path=resolved_path,
    )
