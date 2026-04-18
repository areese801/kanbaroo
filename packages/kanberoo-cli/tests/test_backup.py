"""
Tests for ``kb backup``.

Local-only command: asserts the copied file exists and the warning
path for a non-SQLite URL prints a clear message.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from kanberoo_cli.app import app


def _write_config(config_dir: Path, database_url: str) -> None:
    """
    Overwrite config.toml with a caller-chosen database_url.
    """
    (config_dir / "config.toml").write_text(
        'api_url = "http://test.invalid"\n'
        'token = "kbr_test"\n'
        f'database_url = "{database_url}"\n',
        encoding="utf-8",
    )


def test_backup_copies_sqlite_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    """
    ``kb backup`` copies the configured SQLite file to the output dir
    and the dest file exists with the expected name prefix.
    """
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("KANBEROO_CONFIG_DIR", str(config_dir))
    monkeypatch.delenv("KANBEROO_DATABASE_URL", raising=False)
    db_path = tmp_path / "db" / "kanberoo.db"
    db_path.parent.mkdir()
    db_path.write_bytes(b"fake-sqlite-contents")
    _write_config(config_dir, f"sqlite:///{db_path}")

    out_dir = tmp_path / "out"
    result = runner.invoke(
        app,
        ["backup", "--output", str(out_dir)],
    )
    assert result.exit_code == 0, result.stderr
    produced = list(out_dir.glob("kanberoo-*.db"))
    assert len(produced) == 1
    assert produced[0].read_bytes() == b"fake-sqlite-contents"


def test_backup_warns_on_non_sqlite_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    """
    A non-SQLite ``database_url`` prints a yellow warning and exits 0
    without writing anything.
    """
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    monkeypatch.setenv("KANBEROO_CONFIG_DIR", str(config_dir))
    monkeypatch.delenv("KANBEROO_DATABASE_URL", raising=False)
    _write_config(config_dir, "postgresql://localhost/kanberoo")

    out_dir = tmp_path / "out"
    result = runner.invoke(
        app,
        ["backup", "--output", str(out_dir)],
    )
    assert result.exit_code == 0
    assert "SQLite" in result.stderr
    assert not out_dir.exists() or not any(out_dir.iterdir())
