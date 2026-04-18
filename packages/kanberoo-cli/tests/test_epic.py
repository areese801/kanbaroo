"""
Tests for ``kb epic``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from kanberoo_cli.app import app


def _ws_body() -> dict[str, Any]:
    """
    Canned workspace body for the epic tests.
    """
    return {
        "id": "ws-kan",
        "key": "KAN",
        "name": "KAN",
        "description": None,
        "next_issue_num": 1,
        "created_at": "2026-04-18T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def _epic_body(
    *,
    human_id: str = "KAN-4",
    epic_id: str = "epic-1",
    state: str = "open",
    version: int = 1,
) -> dict[str, Any]:
    """
    Canned epic body.
    """
    return {
        "id": epic_id,
        "workspace_id": "ws-kan",
        "human_id": human_id,
        "title": f"epic {human_id}",
        "description": None,
        "state": state,
        "created_at": "2026-04-18T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
        "deleted_at": None,
        "version": version,
    }


def test_epic_list(mock_api: Any, config_dir: Path, runner: CliRunner) -> None:
    """
    ``kb epic list`` renders a table of epics.
    """
    del config_dir
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/epics",
        body={"items": [_epic_body()], "next_cursor": None},
    )
    result = runner.invoke(app, ["epic", "list", "--workspace", "KAN"])
    assert result.exit_code == 0, result.stderr
    assert "KAN-4" in result.stdout


def test_epic_create(mock_api: Any, config_dir: Path, runner: CliRunner) -> None:
    """
    ``kb epic create`` POSTs the title and renders the created epic.
    """
    del config_dir
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.json(
        "POST",
        "/workspaces/ws-kan/epics",
        body=_epic_body(),
        status_code=201,
        headers={"etag": "1"},
    )
    result = runner.invoke(
        app,
        ["epic", "create", "--workspace", "KAN", "--title", "big"],
    )
    assert result.exit_code == 0, result.stderr
    assert mock_api.requests[-1].body == {"title": "big"}


def test_epic_show_by_key(mock_api: Any, config_dir: Path, runner: CliRunner) -> None:
    """
    ``kb epic show KAN-4`` hits ``GET /epics/by-key/KAN-4``.
    """
    del config_dir
    mock_api.json(
        "GET",
        "/epics/by-key/KAN-4",
        body=_epic_body(),
        headers={"etag": "1"},
    )
    result = runner.invoke(app, ["epic", "show", "KAN-4"])
    assert result.exit_code == 0, result.stderr
    assert "KAN-4" in result.stdout


def test_epic_close(mock_api: Any, config_dir: Path, runner: CliRunner) -> None:
    """
    ``close`` fetches the current ETag and POSTs with If-Match set.
    """
    del config_dir
    mock_api.json(
        "GET",
        "/epics/by-key/KAN-4",
        body=_epic_body(),
        headers={"etag": "1"},
    )
    mock_api.json(
        "GET",
        "/epics/epic-1",
        body=_epic_body(),
        headers={"etag": "1"},
    )
    mock_api.json(
        "POST",
        "/epics/epic-1/close",
        body=_epic_body(state="closed", version=2),
        headers={"etag": "2"},
    )
    result = runner.invoke(app, ["epic", "close", "KAN-4"])
    assert result.exit_code == 0, result.stderr
    close = [r for r in mock_api.requests if r.path == "/epics/epic-1/close"][0]
    assert close.headers["if-match"] == "1"


def test_epic_reopen(mock_api: Any, config_dir: Path, runner: CliRunner) -> None:
    """
    ``reopen`` mirrors ``close``: GET for ETag, then POST.
    """
    del config_dir
    mock_api.json(
        "GET",
        "/epics/by-key/KAN-4",
        body=_epic_body(state="closed", version=2),
        headers={"etag": "2"},
    )
    mock_api.json(
        "GET",
        "/epics/epic-1",
        body=_epic_body(state="closed", version=2),
        headers={"etag": "2"},
    )
    mock_api.json(
        "POST",
        "/epics/epic-1/reopen",
        body=_epic_body(state="open", version=3),
        headers={"etag": "3"},
    )
    result = runner.invoke(app, ["epic", "reopen", "KAN-4"])
    assert result.exit_code == 0, result.stderr
    reopen = [r for r in mock_api.requests if r.path == "/epics/epic-1/reopen"][0]
    assert reopen.headers["if-match"] == "2"
