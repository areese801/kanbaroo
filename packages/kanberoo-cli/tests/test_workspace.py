"""
Tests for ``kb workspace list/create/show``.

Responses are scripted through the :class:`MockApi` fixture in
conftest; every test asserts on both the terminal output and the
request trace the CLI produced.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from kanberoo_cli.app import app


def _ws_body(key: str = "KAN", name: str = "Kanberoo") -> dict[str, object]:
    """
    Build a canned workspace body matching the ``WorkspaceRead`` shape.
    """
    return {
        "id": f"00000000-0000-0000-0000-{key:0>12}",
        "key": key,
        "name": name,
        "description": None,
        "next_issue_num": 1,
        "created_at": "2026-04-18T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def test_list_workspaces_renders_table(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
) -> None:
    """
    Happy path: server returns a single workspace page, CLI renders
    it as a Rich table and exits 0.
    """
    del config_dir
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_ws_body("KAN", "Kanberoo")], "next_cursor": None},
    )
    result = runner.invoke(app, ["workspace", "list"])
    assert result.exit_code == 0, result.stderr
    assert "KAN" in result.stdout
    assert "Kanberoo" in result.stdout


def test_list_workspaces_empty_shows_none_placeholder(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
) -> None:
    """
    An empty list still renders a single ``(none)`` row instead of a
    blank table.
    """
    del config_dir
    mock_api.json("GET", "/workspaces", body={"items": [], "next_cursor": None})
    result = runner.invoke(app, ["workspace", "list"])
    assert result.exit_code == 0, result.stderr
    assert "(none)" in result.stdout


def test_list_workspaces_json_output(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
) -> None:
    """
    ``--json`` emits the decoded list body directly on stdout.
    """
    del config_dir
    item = _ws_body("KAN", "Kanberoo")
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [item], "next_cursor": None},
    )
    result = runner.invoke(app, ["workspace", "list", "--json"])
    assert result.exit_code == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert decoded == [item]


def test_create_workspace_posts_payload(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
) -> None:
    """
    ``create`` sends a POST with the flag values, attaches the bearer
    token, and renders the created workspace.
    """
    del config_dir
    mock_api.json(
        "POST",
        "/workspaces",
        body=_ws_body("KAN", "Kanberoo"),
        status_code=201,
        headers={"etag": "1"},
    )
    result = runner.invoke(
        app,
        ["workspace", "create", "--key", "KAN", "--name", "Kanberoo"],
    )
    assert result.exit_code == 0, result.stderr
    assert mock_api.requests[-1].method == "POST"
    assert mock_api.requests[-1].path == "/workspaces"
    assert mock_api.requests[-1].body == {"key": "KAN", "name": "Kanberoo"}
    assert "Bearer kbr_test" in mock_api.requests[-1].headers["authorization"]


def test_show_workspace_falls_back_to_list_scan(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
) -> None:
    """
    ``show KAN`` first probes ``/workspaces/KAN`` (404), then walks
    the list until it finds a matching key.
    """
    del config_dir
    mock_api.error(
        "GET",
        "/workspaces/KAN",
        status_code=404,
        code="not_found",
        message="workspace KAN not found",
    )
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_ws_body("KAN", "Kanberoo")], "next_cursor": None},
    )
    result = runner.invoke(app, ["workspace", "show", "KAN"])
    assert result.exit_code == 0, result.stderr
    assert "Kanberoo" in result.stdout


def test_show_workspace_missing_exits_nonzero(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
) -> None:
    """
    A completely unknown key exits 1 with a ``not_found`` error on
    stderr.
    """
    del config_dir
    mock_api.error(
        "GET",
        "/workspaces/WAT",
        status_code=404,
        code="not_found",
        message="workspace WAT not found",
    )
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_ws_body("KAN", "Kanberoo")], "next_cursor": None},
    )
    result = runner.invoke(app, ["workspace", "show", "WAT"])
    assert result.exit_code == 1
    assert "not_found" in result.stderr


def test_missing_config_exits_with_hint(
    tmp_path: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    When ``config.toml`` does not exist the CLI exits 1 and points
    the user at ``kb init`` on stderr.
    """
    monkeypatch.setenv("KANBEROO_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("KANBEROO_API_URL", raising=False)
    monkeypatch.delenv("KANBEROO_TOKEN", raising=False)
    monkeypatch.delenv("KANBEROO_DATABASE_URL", raising=False)
    result = runner.invoke(app, ["workspace", "list"])
    assert result.exit_code == 1
    assert "kb init" in result.stderr
