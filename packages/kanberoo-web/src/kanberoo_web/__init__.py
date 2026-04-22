"""
Kanberoo phase 2 web UI.

This package bundles the static web assets (HTML, CSS, JS) for the Kanberoo
web UI. It is served by :mod:`kanberoo_api` via a ``/ui`` static mount when
installed as the ``kanberoo-api[web]`` extra. See ``docs/spec.md`` section
9.2 for design intent.

Milestone M1 of phase 2 ships a placeholder ``index.html``; the real React
SPA lands in M2.
"""

from pathlib import Path

__version__ = "0.2.0"

__all__ = ["web_assets_path"]


def web_assets_path() -> Path:
    """
    Return the filesystem path to the bundled web assets directory.

    The returned path points at the ``dist/`` directory that ships alongside
    this module inside the installed wheel (or the source tree during an
    editable install). Callers should treat the path as read-only and
    mount it via a static-file server.

    :returns: Absolute path to the bundled ``dist`` directory.
    """
    return Path(__file__).resolve().parent / "dist"
