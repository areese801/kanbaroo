"""
Tests for ``kb tag``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from typer.testing import CliRunner

from kanberoo_cli.app import app


def _ws_body() -> dict[str, Any]:
    """
    Canned workspace body for the tag tests.
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


def _tag_body(
    *, tag_id: str = "tag-1", name: str = "bug", color: str | None = "#cc3333"
) -> dict[str, Any]:
    """
    Canned tag body.
    """
    return {
        "id": tag_id,
        "workspace_id": "ws-kan",
        "name": name,
        "color": color,
        "created_at": "2026-04-18T00:00:00Z",
        "deleted_at": None,
    }


def test_tag_list(mock_api: Any, config_dir: Path, runner: CliRunner) -> None:
    """
    ``kb tag list`` renders every tag in the workspace.
    """
    del config_dir
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/tags",
        body={"items": [_tag_body()]},
    )
    result = runner.invoke(app, ["tag", "list", "--workspace", "KAN"])
    assert result.exit_code == 0, result.stderr
    assert "bug" in result.stdout


def test_tag_create(mock_api: Any, config_dir: Path, runner: CliRunner) -> None:
    """
    ``kb tag create`` POSTs the name and optional color.
    """
    del config_dir
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.json(
        "POST",
        "/workspaces/ws-kan/tags",
        body=_tag_body(),
        status_code=201,
    )
    result = runner.invoke(
        app,
        ["tag", "create", "bug", "--workspace", "KAN", "--color", "#cc3333"],
    )
    assert result.exit_code == 0, result.stderr
    assert mock_api.requests[-1].body == {"name": "bug", "color": "#cc3333"}


def test_tag_rename(mock_api: Any, config_dir: Path, runner: CliRunner) -> None:
    """
    ``kb tag rename`` PATCHes the tag with its new name (no If-Match
    because tags are not versioned).
    """
    del config_dir
    mock_api.json(
        "PATCH",
        "/tags/tag-1",
        body=_tag_body(name="defect"),
    )
    result = runner.invoke(app, ["tag", "rename", "tag-1", "defect"])
    assert result.exit_code == 0, result.stderr
    assert "if-match" not in mock_api.requests[-1].headers
    assert mock_api.requests[-1].body == {"name": "defect"}


def test_tag_delete(mock_api: Any, config_dir: Path, runner: CliRunner) -> None:
    """
    ``kb tag delete`` with ``--yes`` hits the soft-delete endpoint
    without a confirmation prompt.
    """
    del config_dir

    def _delete(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    mock_api.add("DELETE", "/tags/tag-1", _delete)
    result = runner.invoke(app, ["tag", "delete", "tag-1", "--yes"])
    assert result.exit_code == 0, result.stderr
    assert any(r.method == "DELETE" for r in mock_api.requests)
