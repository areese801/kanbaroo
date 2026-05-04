"""
Tests for ``kb project init``.

Each test points the cwd, the home dir, and ``KANBAROO_CONFIG_DIR`` at
``tmp_path`` so the command writes everything inside the test sandbox.
The HTTP layer is exercised through the existing :class:`MockApi`
fixture (see ``conftest.py``); the command's filesystem side effects
(token file under ``~/.kanbaroo/tokens/`` and project-root
``.mcp.json``) are inspected directly.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from kanbaroo_cli.app import app
from kanbaroo_cli.commands.project import (
    _key_from_basename,
    _name_from_basename,
    _slug_from_basename,
)


def _workspace_body(*, key: str = "DIFFDONK") -> dict[str, Any]:
    """
    Canned ``WorkspaceRead`` body returned by the fake server's POST
    handler. Only the fields the project-init flow inspects are
    populated; the rest are filler so the schema reads as plausible.
    """
    return {
        "id": "ws-1",
        "key": key,
        "name": "Diff Donkey",
        "description": None,
        "next_issue_num": 1,
        "created_at": "2026-05-04T00:00:00Z",
        "updated_at": "2026-05-04T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def _token_body(*, plaintext: str = "kbr_minted") -> dict[str, Any]:
    """
    Canned ``TokenRead`` body with the ``plaintext`` field included so
    the create path returns a usable secret.
    """
    return {
        "id": "tok-1",
        "token_hash": "deadbeef",
        "actor_type": "claude",
        "actor_id": "claude-diff-donkey",
        "name": "Diff Donkey outer Claude",
        "created_at": "2026-05-04T00:00:00Z",
        "last_used_at": None,
        "revoked_at": None,
        "plaintext": plaintext,
    }


@pytest.fixture
def project_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Path:
    """
    Create a ``diff-donkey/`` project directory inside ``tmp_path``,
    chdir into it, and pin ``$HOME`` to ``tmp_path / "home"`` so the
    command's filesystem side effects land in the sandbox.

    ``$KANBAROO_CONFIG_DIR`` is set by the shared ``config_dir``
    fixture and continues to point at ``tmp_path`` itself, so the
    command's token file lands at ``tmp_path/tokens/<actor-id>``.
    """
    project = tmp_path / "diff-donkey"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("HOME", str(home))
    return project


def _token_file_for(config_root: Path, actor_id: str) -> Path:
    """
    Resolve the on-disk token path the command will write to.

    The CLI's ``default_config_dir`` honors ``$KANBAROO_CONFIG_DIR``
    (set to ``tmp_path`` by ``config_dir``); tokens live at
    ``<config_dir>/tokens/<actor-id>``.
    """
    return (config_root / "tokens" / actor_id).resolve()


def test_slug_helpers_basic() -> None:
    """
    Slug derivation: ``diff-donkey`` -> ``DIFFDONK`` /
    ``claude-diff-donkey`` / ``Diff Donkey``.
    """
    assert _key_from_basename("diff-donkey") == "DIFFDONK"
    assert _slug_from_basename("diff-donkey") == "diff-donkey"
    assert _name_from_basename("diff-donkey") == "Diff Donkey"


def test_slug_helpers_truncates_to_eight_chars() -> None:
    """
    Long bases truncate to eight alphanumeric chars after sanitization.
    """
    assert _key_from_basename("very-long-project-name") == "VERYLONG"


def test_slug_helpers_unicode_and_punctuation() -> None:
    """
    Unicode and punctuation are sanitized rather than crashing.

    Non-ASCII characters do not match ``[A-Z0-9]`` after upper-casing,
    so they drop out of the workspace key entirely; the slug helper
    treats any run of non-alphanumeric ASCII as a single ``-``.
    """
    # café_bär!! -> upper: CAFÉ_BÄR!! -> filtered to ASCII alnum: CAFBR
    assert _key_from_basename("café_bär!!") == "CAFBR"
    assert _slug_from_basename("café bar.") == "caf-bar"
    assert _name_from_basename("hello.world_foo") == "Hello World Foo"


def test_slug_helpers_empty_falls_back_to_project() -> None:
    """
    Inputs that produce no usable characters fall back to a sensible
    default rather than empty strings.
    """
    assert _key_from_basename("...") == "PROJECT"
    assert _slug_from_basename("...") == "project"
    assert _name_from_basename("") == "Project"


def test_project_init_dry_run_writes_nothing(
    mock_api: Any,
    config_dir: Path,
    project_dir: Path,
    runner: CliRunner,
) -> None:
    """
    ``--dry-run`` skips every state change. No HTTP traffic, no token
    file, no ``.mcp.json``.
    """
    result = runner.invoke(app, ["project", "init", "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["workspace"]["status"] == "planned"
    assert payload["token"]["status"] == "planned"
    assert payload["mcp_json"]["status"] == "planned"
    assert mock_api.requests == []
    assert not (project_dir / ".mcp.json").exists()
    assert not (config_dir / "tokens").exists()


def test_project_init_happy_path(
    mock_api: Any,
    config_dir: Path,
    project_dir: Path,
    runner: CliRunner,
) -> None:
    """
    Happy path: workspace POST + token POST happen in order, the
    plaintext lands in ``<config dir>/tokens/<actor-id>`` at mode 0600,
    and ``.mcp.json`` carries the absolute token path with the right
    flags.
    """
    mock_api.json("POST", "/workspaces", body=_workspace_body(), status_code=201)
    mock_api.json("POST", "/tokens", body=_token_body(), status_code=201)

    result = runner.invoke(app, ["project", "init", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["workspace"]["key"] == "DIFFDONK"
    assert payload["workspace"]["status"] == "created"
    assert payload["token"]["status"] == "written"
    assert payload["mcp_json"]["status"] == "written"
    assert payload["token"]["actor_id"] == "claude-diff-donkey"

    workspace_request = mock_api.requests[0]
    assert workspace_request.method == "POST"
    assert workspace_request.path == "/workspaces"
    assert workspace_request.body == {
        "key": "DIFFDONK",
        "name": "Diff Donkey",
    }
    token_request = mock_api.requests[1]
    assert token_request.method == "POST"
    assert token_request.path == "/tokens"
    assert token_request.body == {
        "name": "Diff Donkey outer Claude",
        "actor_type": "claude",
        "actor_id": "claude-diff-donkey",
    }

    token_file = _token_file_for(config_dir, "claude-diff-donkey")
    assert token_file.read_text(encoding="utf-8") == "kbr_minted\n"
    mode_bits = stat.S_IMODE(token_file.stat().st_mode)
    assert mode_bits == 0o600, oct(mode_bits)

    mcp_path = project_dir / ".mcp.json"
    assert mcp_path.exists()
    body = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert body == {
        "mcpServers": {
            "kanbaroo": {
                "type": "stdio",
                "command": "kanbaroo-mcp",
                "args": [
                    "--api-url",
                    "http://test.invalid",
                    "--token-file",
                    str(token_file),
                ],
            }
        }
    }
    raw = mcp_path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert "  " in raw  # two-space indent


def test_project_init_workspace_409_is_idempotent(
    mock_api: Any,
    config_dir: Path,
    project_dir: Path,
    runner: CliRunner,
) -> None:
    """
    A 409 from ``POST /workspaces`` is treated as "already exists" and
    the rest of the flow proceeds.
    """
    del project_dir
    mock_api.error(
        "POST",
        "/workspaces",
        status_code=409,
        code="conflict",
        message="workspace key already exists",
    )
    mock_api.json("POST", "/tokens", body=_token_body(), status_code=201)

    result = runner.invoke(app, ["project", "init", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["workspace"]["status"] == "exists"
    assert payload["token"]["status"] == "written"
    assert payload["status"] == "ok"


def test_project_init_existing_token_file_blocks_without_force(
    mock_api: Any,
    config_dir: Path,
    project_dir: Path,
    runner: CliRunner,
) -> None:
    """
    With an existing token file and no ``--force``, ``--json`` mode
    fails fast with a stable ``token_file_exists`` error code and never
    issues HTTP traffic.
    """
    del project_dir
    token_file = _token_file_for(config_dir, "claude-diff-donkey")
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("pre-existing\n", encoding="utf-8")

    result = runner.invoke(app, ["project", "init", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    codes = [err["code"] for err in payload["errors"]]
    assert "token_file_exists" in codes
    assert mock_api.requests == []
    assert token_file.read_text(encoding="utf-8") == "pre-existing\n"


def test_project_init_force_overwrites_existing_token_file(
    mock_api: Any,
    config_dir: Path,
    project_dir: Path,
    runner: CliRunner,
) -> None:
    """
    ``--force`` overwrites an existing token file and proceeds with
    the workspace + token calls.
    """
    del project_dir
    token_file = _token_file_for(config_dir, "claude-diff-donkey")
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("pre-existing\n", encoding="utf-8")
    mock_api.json("POST", "/workspaces", body=_workspace_body(), status_code=201)
    mock_api.json(
        "POST",
        "/tokens",
        body=_token_body(plaintext="kbr_replaced"),
        status_code=201,
    )

    result = runner.invoke(app, ["project", "init", "--json", "--force"])
    assert result.exit_code == 0, result.output
    assert token_file.read_text(encoding="utf-8") == "kbr_replaced\n"


def test_project_init_existing_mcp_json_blocks_without_force(
    mock_api: Any,
    config_dir: Path,
    project_dir: Path,
    runner: CliRunner,
) -> None:
    """
    Existing ``.mcp.json`` blocks the command without ``--force``.
    """
    del config_dir
    existing = project_dir / ".mcp.json"
    existing.write_text('{"mcpServers": {}}\n', encoding="utf-8")

    result = runner.invoke(app, ["project", "init", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    codes = [err["code"] for err in payload["errors"]]
    assert "mcp_json_exists" in codes
    assert existing.read_text(encoding="utf-8") == '{"mcpServers": {}}\n'
    assert mock_api.requests == []


def test_project_init_overrides_take_effect(
    mock_api: Any,
    config_dir: Path,
    project_dir: Path,
    runner: CliRunner,
) -> None:
    """
    Explicit ``--key``, ``--name``, ``--actor-id``, ``--token-name``
    and ``--api-url`` overrides flow through to the workspace and token
    POST bodies and into the rendered ``.mcp.json``.
    """
    mock_api.json(
        "POST",
        "/workspaces",
        body=_workspace_body(key="OVR"),
        status_code=201,
    )
    mock_api.json("POST", "/tokens", body=_token_body(), status_code=201)

    result = runner.invoke(
        app,
        [
            "project",
            "init",
            "--key",
            "OVR",
            "--name",
            "Override Project",
            "--actor-id",
            "claude-override",
            "--token-name",
            "Override Claude",
            "--api-url",
            "http://overridden.invalid",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    workspace_request = mock_api.requests[0]
    assert workspace_request.body == {
        "key": "OVR",
        "name": "Override Project",
    }
    token_request = mock_api.requests[1]
    assert token_request.body == {
        "name": "Override Claude",
        "actor_type": "claude",
        "actor_id": "claude-override",
    }
    mcp_body = json.loads((project_dir / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp_body["mcpServers"]["kanbaroo"]["args"][1] == "http://overridden.invalid"
    expected_token = _token_file_for(config_dir, "claude-override")
    assert mcp_body["mcpServers"]["kanbaroo"]["args"][3] == str(expected_token)


def test_project_init_json_includes_next_steps_and_notes(
    mock_api: Any,
    config_dir: Path,
    project_dir: Path,
    runner: CliRunner,
) -> None:
    """
    The ``--json`` payload always includes ``next_steps``; when the
    Claude Code probe cannot confirm support it also surfaces a
    ``notes`` entry.
    """
    del config_dir, project_dir
    mock_api.json("POST", "/workspaces", body=_workspace_body(), status_code=201)
    mock_api.json("POST", "/tokens", body=_token_body(), status_code=201)

    result = runner.invoke(app, ["project", "init", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert isinstance(payload["next_steps"], list)
    assert any("Restart Claude Code" in step for step in payload["next_steps"])
    assert isinstance(payload["notes"], list)
