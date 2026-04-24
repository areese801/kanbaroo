"""
Tests for ``kb audit``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from kanbaroo_cli.app import app


def _story_body(human_id: str = "KAN-1") -> dict[str, Any]:
    """
    Canned story body for the audit command's entity resolution.
    """
    return {
        "id": "story-1",
        "workspace_id": "ws-kan",
        "epic_id": None,
        "human_id": human_id,
        "title": "x",
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


def test_audit_renders_history(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    Happy path: entity resolves to a story, audit endpoint returns a
    list of events, CLI renders the table.
    """
    del config_dir
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=_story_body(),
        headers={"etag": "1"},
    )
    mock_api.json(
        "GET",
        "/audit/entity/story/story-1",
        body={
            "items": [
                {
                    "id": "ev-1",
                    "occurred_at": "2026-04-18T00:00:00Z",
                    "actor_type": "human",
                    "actor_id": "adam",
                    "entity_type": "story",
                    "entity_id": "story-1",
                    "action": "created",
                    "diff": {},
                }
            ]
        },
    )
    result = runner.invoke(app, ["audit", "KAN-1"])
    assert result.exit_code == 0, result.stderr
    assert "created" in result.stdout


def test_audit_unknown_story_errors(
    mock_api: Any, config_dir: Path, runner: CliRunner
) -> None:
    """
    When the handle resolves to nothing the CLI exits 1 with a
    ``not_found`` message on stderr.
    """
    del config_dir
    mock_api.error(
        "GET",
        "/stories/by-key/WAT-1",
        status_code=404,
        code="not_found",
        message="story WAT-1 not found",
    )
    mock_api.error(
        "GET",
        "/epics/by-key/WAT-1",
        status_code=404,
        code="not_found",
        message="epic WAT-1 not found",
    )
    result = runner.invoke(app, ["audit", "WAT-1"])
    assert result.exit_code == 1
    assert "not_found" in result.stderr
