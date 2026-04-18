"""
Tests for ``kb tag``.
"""

from __future__ import annotations

import json
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


def test_tag_list_hides_soft_deleted_by_default(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    By default the listing hides soft-deleted tags and prints a hint
    line when any exist so the operator knows to pass
    ``--include-deleted``.
    """
    del config_dir
    live = _tag_body(tag_id="tag-live", name="bug")
    gone = _tag_body(tag_id="tag-gone", name="retired", color=None)
    gone["deleted_at"] = "2026-04-18T00:00:00Z"
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/tags",
        body={"items": [live, gone]},
    )
    result = runner.invoke(app, ["tag", "list", "--workspace", "KAN"])
    assert result.exit_code == 0, result.stderr
    assert "bug" in result.stdout
    assert "retired" not in result.stdout
    assert "1 soft-deleted tag" in result.stdout
    assert "--include-deleted" in result.stdout


def test_tag_list_include_deleted_flag(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    ``--include-deleted`` lists soft-deleted tags and suppresses the
    "not shown" hint.
    """
    del config_dir
    live = _tag_body(tag_id="tag-live", name="bug")
    gone = _tag_body(tag_id="tag-gone", name="retired", color=None)
    gone["deleted_at"] = "2026-04-18T00:00:00Z"
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/tags",
        body={"items": [live, gone]},
    )
    result = runner.invoke(
        app,
        ["tag", "list", "--workspace", "KAN", "--include-deleted"],
    )
    assert result.exit_code == 0, result.stderr
    assert "bug" in result.stdout
    assert "retired" in result.stdout
    assert "not shown" not in result.stdout


def test_tag_create(mock_api: Any, config_dir: Path, runner: CliRunner) -> None:
    """
    ``kb tag create`` POSTs the name and optional color.
    """
    del config_dir
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/tags/similar",
        body={"items": []},
    )
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


def test_tag_create_force_skips_prompt_with_similar(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    With ``--force`` the CLI ignores duplicate matches.
    """
    del config_dir
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/tags/similar",
        body={"items": [_tag_body(name="UI")]},
    )
    mock_api.json(
        "POST",
        "/workspaces/ws-kan/tags",
        body=_tag_body(name="ui"),
        status_code=201,
    )
    result = runner.invoke(
        app,
        ["tag", "create", "ui", "--workspace", "KAN", "--force"],
    )
    assert result.exit_code == 0, result.stderr
    posts = [r for r in mock_api.requests if r.method == "POST"]
    assert posts and posts[0].path == "/workspaces/ws-kan/tags"


def test_tag_create_prompt_reject_aborts(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    Answering ``n`` aborts the create.
    """
    del config_dir
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/tags/similar",
        body={"items": [_tag_body(name="UI")]},
    )
    result = runner.invoke(
        app,
        ["tag", "create", "ui", "--workspace", "KAN"],
        input="n\n",
    )
    assert result.exit_code == 1
    posts = [
        r
        for r in mock_api.requests
        if r.method == "POST" and r.path == "/workspaces/ws-kan/tags"
    ]
    assert posts == []


def test_tag_create_json_includes_warnings(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    With ``--json`` the CLI never prompts and folds the matches into
    ``warnings`` on the result.
    """
    del config_dir
    similar = _tag_body(name="UI")
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/tags/similar",
        body={"items": [similar]},
    )
    mock_api.json(
        "POST",
        "/workspaces/ws-kan/tags",
        body=_tag_body(name="ui", tag_id="tag-2"),
        status_code=201,
    )
    result = runner.invoke(
        app,
        ["tag", "create", "ui", "--workspace", "KAN", "--json"],
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["id"] == "tag-2"
    assert payload["warnings"] == {"similar": [similar["id"]]}


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
