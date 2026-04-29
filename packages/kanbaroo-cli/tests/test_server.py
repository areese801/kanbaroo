"""
Tests for ``kb server start/stop``.

The commands shell out to ``docker compose``; we mock
:func:`subprocess.run` via monkeypatch and assert on the argv the CLI
would have invoked. No actual docker process is started.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from kanbaroo_cli.app import app
from kanbaroo_cli.commands import server as server_command


def test_server_start_invokes_docker_compose_up(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    """
    ``kb server start`` calls ``docker compose up -d`` via
    ``subprocess.run``. No ``$KANBAROO_COMPOSE_FILE`` means no ``-f``.
    """
    monkeypatch.delenv("KANBAROO_COMPOSE_FILE", raising=False)
    monkeypatch.setenv("KANBAROO_DATA_DIR", str(tmp_path / "data"))
    captured: list[list[str]] = []

    def _fake_run(argv: list[str], **_kwargs: Any) -> Any:
        captured.append(argv)

        class _Completed:
            returncode = 0

        return _Completed()

    monkeypatch.setattr(server_command.subprocess, "run", _fake_run)
    result = runner.invoke(app, ["server", "start"])
    assert result.exit_code == 0, result.stderr
    assert captured == [["docker", "compose", "up", "-d"]]


def test_server_start_passes_compose_file_override(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    """
    ``$KANBAROO_COMPOSE_FILE`` flows through to ``-f`` in the docker
    compose invocation.
    """
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text("version: '3'\n", encoding="utf-8")
    monkeypatch.setenv("KANBAROO_COMPOSE_FILE", str(compose_path))
    monkeypatch.setenv("KANBAROO_DATA_DIR", str(tmp_path / "data"))
    captured: list[list[str]] = []

    def _fake_run(argv: list[str], **_kwargs: Any) -> Any:
        captured.append(argv)

        class _Completed:
            returncode = 0

        return _Completed()

    monkeypatch.setattr(server_command.subprocess, "run", _fake_run)
    result = runner.invoke(app, ["server", "start"])
    assert result.exit_code == 0, result.stderr
    assert captured == [["docker", "compose", "-f", str(compose_path), "up", "-d"]]


def test_server_stop_invokes_docker_compose_down(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    """
    ``kb server stop`` calls ``docker compose down``.
    """
    monkeypatch.delenv("KANBAROO_COMPOSE_FILE", raising=False)
    monkeypatch.setenv("KANBAROO_DATA_DIR", str(tmp_path / "data"))
    captured: list[list[str]] = []

    def _fake_run(argv: list[str], **_kwargs: Any) -> Any:
        captured.append(argv)

        class _Completed:
            returncode = 0

        return _Completed()

    monkeypatch.setattr(server_command.subprocess, "run", _fake_run)
    result = runner.invoke(app, ["server", "stop"])
    assert result.exit_code == 0, result.stderr
    assert captured == [["docker", "compose", "down"]]


def test_server_start_failure_surfaces_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    """
    A failing compose subprocess surfaces its exit code through the
    CLI.
    """
    monkeypatch.delenv("KANBAROO_COMPOSE_FILE", raising=False)
    monkeypatch.setenv("KANBAROO_DATA_DIR", str(tmp_path / "data"))

    def _fake_run(argv: list[str], **_kwargs: Any) -> Any:
        raise subprocess.CalledProcessError(returncode=2, cmd=argv)

    monkeypatch.setattr(server_command.subprocess, "run", _fake_run)
    result = runner.invoke(app, ["server", "start"])
    assert result.exit_code == 2
    assert "docker compose up failed" in result.stderr


def test_server_start_wait_without_database_url_in_config(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    """
    ``kb server start --wait`` only needs ``api_url`` + ``token``. A
    ``config.toml`` missing ``database_url`` must not blow up on the
    wait path; the HTTP probe is all that runs.
    """
    monkeypatch.setenv("KANBAROO_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("KANBAROO_API_URL", raising=False)
    monkeypatch.delenv("KANBAROO_TOKEN", raising=False)
    monkeypatch.delenv("KANBAROO_DATABASE_URL", raising=False)
    monkeypatch.delenv("KANBAROO_COMPOSE_FILE", raising=False)
    monkeypatch.setenv("KANBAROO_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "config.toml").write_text(
        'api_url = "http://test.invalid"\n'
        'token = "kbr_test"\n'
        'default_workspace = "KAN"\n',
        encoding="utf-8",
    )

    def _fake_run(argv: list[str], **_kwargs: Any) -> Any:
        class _Completed:
            returncode = 0

        return _Completed()

    monkeypatch.setattr(server_command.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        server_command,
        "_poll_until_ready",
        lambda **_kwargs: True,
    )
    result = runner.invoke(app, ["server", "start", "--wait"])
    assert result.exit_code == 0, result.stderr
    assert "server started" in result.stdout.lower()


def test_server_start_passes_user_data_dir_through_env(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    """
    A user-exported ``$KANBAROO_DATA_DIR`` flows verbatim into the
    docker-compose subprocess env and the directory is created.
    """
    monkeypatch.delenv("KANBAROO_COMPOSE_FILE", raising=False)
    user_data_dir = tmp_path / "user-data-dir"
    monkeypatch.setenv("KANBAROO_DATA_DIR", str(user_data_dir))
    captured_envs: list[dict[str, str]] = []

    def _fake_run(argv: list[str], **kwargs: Any) -> Any:
        del argv
        captured_envs.append(kwargs.get("env") or {})

        class _Completed:
            returncode = 0

        return _Completed()

    monkeypatch.setattr(server_command.subprocess, "run", _fake_run)
    result = runner.invoke(app, ["server", "start"])
    assert result.exit_code == 0, result.stderr
    assert captured_envs[0]["KANBAROO_DATA_DIR"] == str(user_data_dir)
    assert user_data_dir.is_dir()


def test_server_start_injects_default_data_dir_when_unset(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    """
    With no exported ``$KANBAROO_DATA_DIR`` the platform default from
    :func:`kanbaroo_cli.paths.resolve_data_dir` is injected into the
    subprocess env.
    """
    monkeypatch.delenv("KANBAROO_COMPOSE_FILE", raising=False)
    monkeypatch.delenv("KANBAROO_DATA_DIR", raising=False)
    fake_default = tmp_path / "platform-default"

    monkeypatch.setattr(
        server_command,
        "resolve_data_dir",
        lambda: fake_default,
    )

    captured_envs: list[dict[str, str]] = []

    def _fake_run(argv: list[str], **kwargs: Any) -> Any:
        del argv
        captured_envs.append(kwargs.get("env") or {})

        class _Completed:
            returncode = 0

        return _Completed()

    monkeypatch.setattr(server_command.subprocess, "run", _fake_run)
    result = runner.invoke(app, ["server", "start"])
    assert result.exit_code == 0, result.stderr
    assert captured_envs[0]["KANBAROO_DATA_DIR"] == str(fake_default)
    assert fake_default.is_dir()
