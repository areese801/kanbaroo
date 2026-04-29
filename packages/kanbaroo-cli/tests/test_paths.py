"""
Tests for :mod:`kanbaroo_cli.paths`.

The helper has to make a platform decision based on ``sys.platform``
and a handful of env vars. We monkeypatch both so the tests run
identically on whatever host actually executes them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kanbaroo_cli.paths import default_data_dir, resolve_data_dir


def _scrub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Drop every env var the helper might consult so each test starts
    from a known-empty baseline.
    """
    for var in (
        "KANBAROO_DATA_DIR",
        "XDG_DATA_HOME",
        "LOCALAPPDATA",
        "USERPROFILE",
    ):
        monkeypatch.delenv(var, raising=False)


def test_default_data_dir_macos(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    macOS picks ``~/Library/Application Support/Kanbaroo``.
    """
    _scrub_env(monkeypatch)
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert (
        default_data_dir() == tmp_path / "Library" / "Application Support" / "Kanbaroo"
    )


def test_default_data_dir_linux_with_xdg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    On Linux ``$XDG_DATA_HOME`` is honored when set.
    """
    _scrub_env(monkeypatch)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "custom-xdg"))
    assert default_data_dir() == tmp_path / "custom-xdg" / "kanbaroo"


def test_default_data_dir_linux_without_xdg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Without ``$XDG_DATA_HOME`` the Linux default is
    ``~/.local/share/kanbaroo``.
    """
    _scrub_env(monkeypatch)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_data_dir() == tmp_path / ".local" / "share" / "kanbaroo"


def test_default_data_dir_linux_variant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    ``sys.platform`` for Linux variants always begins with ``linux``
    (e.g. ``linux2`` on legacy Pythons). The helper still picks the
    Linux branch.
    """
    _scrub_env(monkeypatch)
    monkeypatch.setattr("sys.platform", "linux2")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_data_dir() == tmp_path / ".local" / "share" / "kanbaroo"


def test_default_data_dir_windows_with_localappdata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Windows picks ``%LOCALAPPDATA%/Kanbaroo`` when the env var is set.
    """
    _scrub_env(monkeypatch)
    monkeypatch.setattr("sys.platform", "win32")
    local = tmp_path / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert default_data_dir() == local / "Kanbaroo"


def test_default_data_dir_windows_without_localappdata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Without ``%LOCALAPPDATA%`` Windows falls back to
    ``%USERPROFILE%/AppData/Local/Kanbaroo``.
    """
    _scrub_env(monkeypatch)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "Users" / "alice"))
    assert (
        default_data_dir()
        == tmp_path / "Users" / "alice" / "AppData" / "Local" / "Kanbaroo"
    )


def test_default_data_dir_unknown_platform(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Unknown / BSD-ish platforms fall back to the XDG-style default.
    """
    _scrub_env(monkeypatch)
    monkeypatch.setattr("sys.platform", "freebsd13")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_data_dir() == tmp_path / ".local" / "share" / "kanbaroo"


def test_resolve_data_dir_uses_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    ``$KANBAROO_DATA_DIR`` overrides the platform default on every
    platform.
    """
    _scrub_env(monkeypatch)
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    override = tmp_path / "elsewhere"
    monkeypatch.setenv("KANBAROO_DATA_DIR", str(override))
    assert resolve_data_dir() == override


def test_resolve_data_dir_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Without the override the resolver delegates to
    :func:`default_data_dir`.
    """
    _scrub_env(monkeypatch)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert resolve_data_dir() == tmp_path / ".local" / "share" / "kanbaroo"


def test_resolve_data_dir_does_not_create_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    The resolver is purely informational: it must not create the
    directory itself. Callers are expected to ``mkdir -p`` the path.
    """
    _scrub_env(monkeypatch)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    target = resolve_data_dir()
    assert not target.exists()
