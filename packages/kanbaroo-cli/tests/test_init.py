"""
Tests for ``kb init``.

Each test points ``KANBAROO_CONFIG_DIR`` at a pytest-provided ``tmp_path``
so the command never touches the real home directory. The assertions
cover: first-run creates config and db; re-run without ``--force`` is a
clean error; ``--force`` overwrites the config and issues a second
token.
"""

import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kanbaroo_cli.app import app


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CliRunner:
    """
    Yield a Typer CliRunner with ``KANBAROO_CONFIG_DIR`` redirected to
    ``tmp_path`` and ``KANBAROO_DATABASE_URL`` cleared, so the command
    writes everything under the test's sandbox.
    """
    monkeypatch.setenv("KANBAROO_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("KANBAROO_DATABASE_URL", raising=False)
    return CliRunner()


def _read_token_from_config(config_path: Path) -> str:
    """
    Minimal parser: find the ``token = "..."`` line in config.toml.
    """
    for line in config_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("token = "):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError(f"token not found in {config_path}")


def test_init_creates_config_db_and_token(runner: CliRunner, tmp_path: Path) -> None:
    """
    First-run happy path: config.toml + db file exist, db has applied
    the initial migration, and a human api_tokens row is present.
    """
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output

    config_path = tmp_path / "config.toml"
    db_path = tmp_path / "kanbaroo.db"
    assert config_path.exists()
    assert db_path.exists()

    token = _read_token_from_config(config_path)
    assert token.startswith("kbr_")

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='alembic_version'"
        )
        assert cursor.fetchone() is not None, "alembic_version table should exist"

        cursor = conn.execute("SELECT actor_type, actor_id, name FROM api_tokens")
        rows = cursor.fetchall()
        assert len(rows) == 1
        actor_type, actor_id, token_name = rows[0]
        assert actor_type == "human"
        assert token_name == "personal"
        assert actor_id  # non-empty; OS-dependent default
    finally:
        conn.close()


def test_init_second_run_errors_without_force(
    runner: CliRunner, tmp_path: Path
) -> None:
    """
    Re-running ``kb init`` against an existing config is a clean
    non-zero exit; it does not blow away the config.
    """
    first = runner.invoke(app, ["init"])
    assert first.exit_code == 0
    config_path = tmp_path / "config.toml"
    original_token = _read_token_from_config(config_path)

    second = runner.invoke(app, ["init"])
    assert second.exit_code == 1
    assert "--force" in second.output

    still_original = _read_token_from_config(config_path)
    assert still_original == original_token


def test_init_force_overwrites_and_issues_second_token(
    runner: CliRunner, tmp_path: Path
) -> None:
    """
    With ``--force``, the config is overwritten and a fresh token is
    appended to the api_tokens table. The previous token's row is left
    alone (not revoked).
    """
    first = runner.invoke(app, ["init"])
    assert first.exit_code == 0
    config_path = tmp_path / "config.toml"
    db_path = tmp_path / "kanbaroo.db"
    first_token = _read_token_from_config(config_path)

    second = runner.invoke(
        app, ["init", "--force", "--actor-id", "alice", "--name", "mcp"]
    )
    assert second.exit_code == 0, second.output
    second_token = _read_token_from_config(config_path)

    assert second_token != first_token
    assert second_token.startswith("kbr_")

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT actor_type, actor_id, name, revoked_at "
            "FROM api_tokens ORDER BY created_at"
        )
        rows = cursor.fetchall()
        assert len(rows) == 2
        assert all(row[0] == "human" for row in rows)
        assert all(row[3] is None for row in rows)
        second_row = rows[1]
        assert second_row[1] == "alice"
        assert second_row[2] == "mcp"
    finally:
        conn.close()
