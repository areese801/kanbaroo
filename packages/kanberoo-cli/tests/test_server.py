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

from kanberoo_cli.app import app
from kanberoo_cli.commands import server as server_command


def test_server_start_invokes_docker_compose_up(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    """
    ``kb server start`` calls ``docker compose up -d`` via
    ``subprocess.run``. No ``$KANBEROO_COMPOSE_FILE`` means no ``-f``.
    """
    monkeypatch.delenv("KANBEROO_COMPOSE_FILE", raising=False)
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
    ``$KANBEROO_COMPOSE_FILE`` flows through to ``-f`` in the docker
    compose invocation.
    """
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text("version: '3'\n", encoding="utf-8")
    monkeypatch.setenv("KANBEROO_COMPOSE_FILE", str(compose_path))
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
) -> None:
    """
    ``kb server stop`` calls ``docker compose down``.
    """
    monkeypatch.delenv("KANBEROO_COMPOSE_FILE", raising=False)
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
) -> None:
    """
    A failing compose subprocess surfaces its exit code through the
    CLI.
    """
    monkeypatch.delenv("KANBEROO_COMPOSE_FILE", raising=False)

    def _fake_run(argv: list[str], **_kwargs: Any) -> Any:
        raise subprocess.CalledProcessError(returncode=2, cmd=argv)

    monkeypatch.setattr(server_command.subprocess, "run", _fake_run)
    result = runner.invoke(app, ["server", "start"])
    assert result.exit_code == 2
    assert "docker compose up failed" in result.stderr
