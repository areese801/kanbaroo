"""
Tests for ``kb story``.

Story-related commands use both the ``/stories`` and ``/workspaces``
surfaces, plus the by-key resolver for human ids. The ``edit`` test
points ``$EDITOR`` at ``/bin/true`` so the subprocess is a cheap
no-op that never modifies the buffer, exercising the "no changes,
nothing to do" short circuit.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from kanberoo_cli.app import app

_TRUE_PATH = shutil.which("true") or "/usr/bin/true"


def _ws_body(key: str = "KAN") -> dict[str, Any]:
    """
    Canned workspace body.
    """
    return {
        "id": f"ws-{key.lower()}",
        "key": key,
        "name": f"{key} workspace",
        "description": None,
        "next_issue_num": 1,
        "created_at": "2026-04-18T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def _story_body(
    *,
    human_id: str = "KAN-1",
    story_id: str = "story-1",
    state: str = "backlog",
    version: int = 1,
    description: str | None = None,
) -> dict[str, Any]:
    """
    Canned story body matching the ``StoryRead`` shape.
    """
    return {
        "id": story_id,
        "workspace_id": "ws-kan",
        "epic_id": None,
        "human_id": human_id,
        "title": f"story {human_id}",
        "description": description,
        "priority": "none",
        "state": state,
        "state_actor_type": None,
        "state_actor_id": None,
        "branch_name": None,
        "commit_sha": None,
        "pr_url": None,
        "created_at": "2026-04-18T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
        "deleted_at": None,
        "version": version,
    }


def test_story_list_renders_table(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    Listing stories in a workspace renders their human ids.
    """
    del config_dir
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body("KAN"))
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/stories",
        body={"items": [_story_body(human_id="KAN-1")], "next_cursor": None},
    )
    result = runner.invoke(app, ["story", "list", "--workspace", "KAN"])
    assert result.exit_code == 0, result.stderr
    assert "KAN-1" in result.stdout


def test_story_create_posts_payload(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    ``create`` resolves the workspace then POSTs the payload.
    """
    del config_dir
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body("KAN"))
    mock_api.json(
        "POST",
        "/workspaces/ws-kan/stories",
        body=_story_body(human_id="KAN-7"),
        status_code=201,
        headers={"etag": "1"},
    )
    result = runner.invoke(
        app,
        [
            "story",
            "create",
            "--workspace",
            "KAN",
            "--title",
            "New thing",
            "--priority",
            "high",
        ],
    )
    assert result.exit_code == 0, result.stderr
    last = mock_api.requests[-1]
    assert last.body == {"title": "New thing", "priority": "high"}
    assert last.method == "POST"


def test_story_show_uses_by_key(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    ``show KAN-1`` hits the by-key lookup.
    """
    del config_dir
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=_story_body(human_id="KAN-1"),
        headers={"etag": "1"},
    )
    result = runner.invoke(app, ["story", "show", "KAN-1"])
    assert result.exit_code == 0, result.stderr
    assert "KAN-1" in result.stdout


def test_story_edit_no_change_skips_patch(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    When ``$EDITOR`` exits without modifying the temp file the CLI
    short-circuits with the "no changes" message and does not issue
    a PATCH.
    """
    del config_dir
    monkeypatch.setenv("EDITOR", _TRUE_PATH)
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=_story_body(human_id="KAN-1", description="unchanged"),
        headers={"etag": "1"},
    )
    result = runner.invoke(app, ["story", "edit", "KAN-1"])
    assert result.exit_code == 0, result.stderr
    assert "no changes" in result.stdout
    for req in mock_api.requests:
        assert req.method != "PATCH"


def test_story_edit_applies_patch(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """
    When the editor rewrites the buffer the CLI issues a PATCH with
    the new description and the correct If-Match header.
    """
    del config_dir
    editor_script = tmp_path / "fake_editor.sh"
    editor_script.write_text(
        "#!/usr/bin/env bash\necho 'edited body' > \"$1\"\n",
        encoding="utf-8",
    )
    editor_script.chmod(0o755)
    monkeypatch.setenv("EDITOR", str(editor_script))
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=_story_body(human_id="KAN-1", description="old"),
        headers={"etag": "1"},
    )
    # patch_with_etag first GETs the story by id to read its ETag,
    # then issues the PATCH.
    mock_api.json(
        "GET",
        "/stories/story-1",
        body=_story_body(human_id="KAN-1", description="old"),
        headers={"etag": "1"},
    )
    mock_api.json(
        "PATCH",
        "/stories/story-1",
        body=_story_body(human_id="KAN-1", description="edited body\n", version=2),
        headers={"etag": "2"},
    )
    result = runner.invoke(app, ["story", "edit", "KAN-1"])
    assert result.exit_code == 0, result.stderr
    assert "updated" in result.stdout
    patch_requests = [r for r in mock_api.requests if r.method == "PATCH"]
    assert patch_requests and patch_requests[0].body == {"description": "edited body\n"}
    assert patch_requests[0].headers["if-match"] == "1"


def test_story_move_transition(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    ``move KAN-1 todo`` hits the transition endpoint with If-Match.
    """
    del config_dir
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=_story_body(human_id="KAN-1"),
        headers={"etag": "1"},
    )
    mock_api.json(
        "GET",
        "/stories/story-1",
        body=_story_body(human_id="KAN-1"),
        headers={"etag": "1"},
    )
    mock_api.json(
        "POST",
        "/stories/story-1/transition",
        body=_story_body(human_id="KAN-1", state="todo", version=2),
        headers={"etag": "2"},
    )
    result = runner.invoke(app, ["story", "move", "KAN-1", "todo"])
    assert result.exit_code == 0, result.stderr
    posted = [r for r in mock_api.requests if r.path == "/stories/story-1/transition"]
    assert posted and posted[0].body == {"to_state": "todo"}
    assert posted[0].headers["if-match"] == "1"


def test_story_comment(mock_api: Any, config_dir: Path, runner: CliRunner) -> None:
    """
    ``comment`` POSTs the body to the story's comments endpoint.
    """
    del config_dir
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=_story_body(human_id="KAN-1"),
        headers={"etag": "1"},
    )
    mock_api.json(
        "POST",
        "/stories/story-1/comments",
        body={
            "id": "comment-1",
            "story_id": "story-1",
            "parent_id": None,
            "body": "nice",
            "actor_type": "human",
            "actor_id": "adam",
            "created_at": "2026-04-18T00:00:00Z",
            "updated_at": "2026-04-18T00:00:00Z",
            "deleted_at": None,
            "version": 1,
        },
        status_code=201,
        headers={"etag": "1"},
    )
    result = runner.invoke(app, ["story", "comment", "KAN-1", "nice"])
    assert result.exit_code == 0, result.stderr
    comment_post = mock_api.requests[-1]
    assert comment_post.body == {"body": "nice"}


def test_story_link_creates_linkage(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    ``link KAN-1 blocks KAN-2`` resolves both ids and POSTs to
    ``/linkages``.
    """
    del config_dir
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=_story_body(human_id="KAN-1", story_id="story-1"),
        headers={"etag": "1"},
    )
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-2",
        body=_story_body(human_id="KAN-2", story_id="story-2"),
        headers={"etag": "1"},
    )
    mock_api.json(
        "POST",
        "/linkages",
        body={
            "id": "linkage-1",
            "source_type": "story",
            "source_id": "story-1",
            "target_type": "story",
            "target_id": "story-2",
            "link_type": "blocks",
            "created_at": "2026-04-18T00:00:00Z",
            "deleted_at": None,
        },
        status_code=201,
    )
    result = runner.invoke(app, ["story", "link", "KAN-1", "blocks", "KAN-2"])
    assert result.exit_code == 0, result.stderr
    link_req = mock_api.requests[-1]
    assert link_req.body == {
        "source_type": "story",
        "source_id": "story-1",
        "target_type": "story",
        "target_id": "story-2",
        "link_type": "blocks",
    }


def test_story_delete_with_confirmation(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    ``delete KAN-1`` with ``--yes`` skips the prompt and issues a
    soft delete with If-Match.
    """
    del config_dir
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=_story_body(human_id="KAN-1"),
        headers={"etag": "1"},
    )
    mock_api.json(
        "GET",
        "/stories/story-1",
        body=_story_body(human_id="KAN-1"),
        headers={"etag": "1"},
    )

    def _delete(_request: Any) -> Any:
        import httpx

        return httpx.Response(204)

    mock_api.add("DELETE", "/stories/story-1", _delete)
    result = runner.invoke(app, ["story", "delete", "KAN-1", "--yes"])
    assert result.exit_code == 0, result.stderr
    delete_reqs = [r for r in mock_api.requests if r.method == "DELETE"]
    assert delete_reqs and delete_reqs[0].headers["if-match"] == "1"
