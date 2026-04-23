"""
Tests for ``kb --version`` and ``kb version``.

Both surfaces funnel through :func:`kanberoo_cli.app._installed_version`
so the test swaps that helper's backing ``importlib.metadata.version``
call through monkeypatch. A ``PackageNotFoundError`` path asserts the
``unknown`` fallback.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError

import pytest
from typer.testing import CliRunner

from kanberoo_cli import app as app_module
from kanberoo_cli.app import app


def test_version_flag_prints_installed_version(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    ``kb --version`` prints the installed version and exits 0 without
    invoking a subcommand.
    """
    monkeypatch.setattr(app_module, "_pkg_version", lambda _name: "9.9.9")
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.stderr
    assert "9.9.9" in result.stdout


def test_version_subcommand_prints_installed_version(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    ``kb version`` prints the same string as the flag.
    """
    monkeypatch.setattr(app_module, "_pkg_version", lambda _name: "9.9.9")
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0, result.stderr
    assert "9.9.9" in result.stdout


def test_version_flag_falls_back_to_unknown(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    When the package metadata is missing the flag still exits 0 and
    prints ``unknown``.
    """

    def _missing(_name: str) -> str:
        raise PackageNotFoundError(_name)

    monkeypatch.setattr(app_module, "_pkg_version", _missing)
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.stderr
    assert "unknown" in result.stdout


def test_version_subcommand_falls_back_to_unknown(
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Same ``unknown`` fallback for the subcommand path.
    """

    def _missing(_name: str) -> str:
        raise PackageNotFoundError(_name)

    monkeypatch.setattr(app_module, "_pkg_version", _missing)
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0, result.stderr
    assert "unknown" in result.stdout
