"""
Tests for ``kb epic``.
"""

from __future__ import annotations

import json
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
        "GET",
        "/workspaces/ws-kan/epics/similar",
        body={"items": [], "next_cursor": None},
    )
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


def test_epic_create_force_skips_prompt_with_similar(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    With ``--force`` the CLI ignores duplicate matches and POSTs
    without prompting.
    """
    del config_dir
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/epics/similar",
        body={"items": [_epic_body()], "next_cursor": None},
    )
    mock_api.json(
        "POST",
        "/workspaces/ws-kan/epics",
        body=_epic_body(),
        status_code=201,
        headers={"etag": "1"},
    )
    result = runner.invoke(
        app,
        ["epic", "create", "--workspace", "KAN", "--title", "big", "--force"],
    )
    assert result.exit_code == 0, result.stderr
    posts = [r for r in mock_api.requests if r.method == "POST"]
    assert posts and posts[0].path == "/workspaces/ws-kan/epics"


def test_epic_create_prompt_reject_aborts(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    Answering ``n`` aborts the create.
    """
    del config_dir
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/epics/similar",
        body={"items": [_epic_body()], "next_cursor": None},
    )
    result = runner.invoke(
        app,
        ["epic", "create", "--workspace", "KAN", "--title", "big"],
        input="n\n",
    )
    assert result.exit_code == 1
    posts = [
        r
        for r in mock_api.requests
        if r.method == "POST" and r.path == "/workspaces/ws-kan/epics"
    ]
    assert posts == []


def test_epic_create_json_includes_warnings(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    With ``--json`` the CLI never prompts and folds the matches into
    ``warnings`` on the result.
    """
    del config_dir
    similar = _epic_body()
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/epics/similar",
        body={"items": [similar], "next_cursor": None},
    )
    mock_api.json(
        "POST",
        "/workspaces/ws-kan/epics",
        body=_epic_body(human_id="KAN-9", epic_id="epic-9"),
        status_code=201,
    )
    result = runner.invoke(
        app,
        ["epic", "create", "--workspace", "KAN", "--title", "big", "--json"],
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["id"] == "epic-9"
    assert payload["warnings"] == {"similar": [similar["id"]]}


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


def _story_body_for_epic(
    *,
    human_id: str = "KAN-1",
    story_id: str = "story-1",
) -> dict[str, Any]:
    """
    Minimal story body the epic-show-suggests-story test probes with.
    """
    return {
        "id": story_id,
        "workspace_id": "ws-kan",
        "epic_id": None,
        "human_id": human_id,
        "title": f"story {human_id}",
        "description": None,
        "priority": "none",
        "state": "backlog",
        "state_actor_type": None,
        "state_actor_id": None,
        "branch_name": None,
        "commit_sha": None,
        "pr_url": None,
        "created_at": "2026-04-18T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def test_epic_show_suggests_story_when_ref_is_a_story(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    ``kb epic show KAN-1`` where KAN-1 is a story prints a 404 and a
    hint pointing the user at ``kb story show KAN-1``.
    """
    del config_dir
    mock_api.error(
        "GET",
        "/epics/by-key/KAN-1",
        status_code=404,
        code="not_found",
        message="epic not found",
    )
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=_story_body_for_epic(),
        headers={"etag": "1"},
    )
    result = runner.invoke(app, ["epic", "show", "KAN-1"])
    assert result.exit_code == 1
    assert "404" in result.stderr
    assert "KAN-1 is a story" in result.stderr
    assert "kb story show KAN-1" in result.stderr


def test_epic_show_not_found_when_ref_is_not_a_story_either(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    When neither the epic nor the story lookup hits, the CLI falls back
    to a plain not-found message (no hint row).
    """
    del config_dir
    mock_api.error(
        "GET",
        "/epics/by-key/KAN-99",
        status_code=404,
        code="not_found",
        message="epic not found",
    )
    mock_api.error(
        "GET",
        "/stories/by-key/KAN-99",
        status_code=404,
        code="not_found",
        message="story not found",
    )
    result = runner.invoke(app, ["epic", "show", "KAN-99"])
    assert result.exit_code == 1
    assert "404" in result.stderr
    assert "is a story" not in result.stderr


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
