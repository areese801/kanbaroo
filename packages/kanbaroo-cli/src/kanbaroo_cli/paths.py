"""
Platform-aware filesystem path helpers for the Kanbaroo CLI.

These helpers compute *host-side* paths the CLI needs to know about
when it shells out to Docker — primarily the bind-mount source for the
SQLite database. They live in the CLI package because the only callers
are CLI commands (``kb server start``, ``kb backup``); the API and core
packages run inside the container and never see these paths.

The data directory follows each platform's convention:

- macOS uses ``~/Library/Application Support/Kanbaroo``. That is where
  the system already places per-app data and where Time Machine looks
  for it.
- Linux follows the XDG Base Directory spec: ``$XDG_DATA_HOME`` if set,
  else ``~/.local/share/kanbaroo``.
- Windows uses ``%LOCALAPPDATA%\\Kanbaroo``, falling back to
  ``%USERPROFILE%\\AppData\\Local\\Kanbaroo`` if ``LOCALAPPDATA`` is
  somehow unset.
- Anything else (BSDs, etc.) falls back to the XDG-style default.

Users can always override the resolved path by exporting
``$KANBAROO_DATA_DIR``; that is the public escape hatch for unusual
setups (encrypted volumes, NAS mounts, CI sandboxes).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _macos_default() -> Path:
    """
    Return the macOS default: ``~/Library/Application Support/Kanbaroo``.
    """
    return Path.home() / "Library" / "Application Support" / "Kanbaroo"


def _linux_default() -> Path:
    """
    Return the Linux default: ``$XDG_DATA_HOME/kanbaroo`` if the
    XDG variable is set, else ``~/.local/share/kanbaroo``.
    """
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "kanbaroo"
    return Path.home() / ".local" / "share" / "kanbaroo"


def _windows_default() -> Path:
    """
    Return the Windows default: ``%LOCALAPPDATA%\\Kanbaroo``, falling
    back to ``%USERPROFILE%\\AppData\\Local\\Kanbaroo`` if
    ``LOCALAPPDATA`` is unset.
    """
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Kanbaroo"
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        return Path(user_profile) / "AppData" / "Local" / "Kanbaroo"
    # Last-resort fallback so we never return ``None`` on Windows.
    return Path.home() / "AppData" / "Local" / "Kanbaroo"


def _xdg_style_fallback() -> Path:
    """
    Return the cross-platform fallback used for unknown OSes:
    ``~/.local/share/kanbaroo``. Mirrors the Linux default minus the
    XDG override since other Unix variants tend to honor XDG too.
    """
    return Path.home() / ".local" / "share" / "kanbaroo"


def default_data_dir() -> Path:
    """
    Return the platform-appropriate default Kanbaroo data dir.

    Resolution rules:

    - macOS  (``sys.platform == 'darwin'``)  →
      ``~/Library/Application Support/Kanbaroo``
    - Linux  (``sys.platform.startswith('linux')``)  →
      ``${XDG_DATA_HOME:-$HOME/.local/share}/kanbaroo``
    - Windows  (``sys.platform.startswith('win')``)  →
      ``%LOCALAPPDATA%/Kanbaroo`` (fallback to
      ``%USERPROFILE%/AppData/Local/Kanbaroo``)
    - Anything else  →  ``$HOME/.local/share/kanbaroo``
      (XDG-style fallback)

    Pure function: does not touch the filesystem and does not consult
    ``$KANBAROO_DATA_DIR``. Callers that want the override-aware value
    should use :func:`resolve_data_dir`.
    """
    platform = sys.platform
    if platform == "darwin":
        return _macos_default()
    if platform.startswith("linux"):
        return _linux_default()
    if platform.startswith("win"):
        return _windows_default()
    return _xdg_style_fallback()


def resolve_data_dir() -> Path:
    """
    Return ``$KANBAROO_DATA_DIR`` if set and non-empty, else
    :func:`default_data_dir`.

    Does not create the directory. Callers are responsible for
    ``mkdir -p`` immediately before any operation that needs the path
    to exist (e.g. just before ``docker compose up`` so the bind-mount
    has somewhere to land).
    """
    override = os.environ.get("KANBAROO_DATA_DIR")
    if override:
        return Path(override)
    return default_data_dir()
