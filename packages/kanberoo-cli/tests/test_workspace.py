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


def test_show_workspace_by_key(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
) -> None:
    """
    ``show KAN`` routes straight to ``GET /workspaces/by-key/KAN``
    because the reference contains no dashes.
    """
    del config_dir
    mock_api.json(
        "GET",
        "/workspaces/by-key/KAN",
        body=_ws_body("KAN", "Kanberoo"),
    )
    result = runner.invoke(app, ["workspace", "show", "KAN"])
    assert result.exit_code == 0, result.stderr
    assert "Kanberoo" in result.stdout
    assert mock_api.requests[-1].path == "/workspaces/by-key/KAN"


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
        "/workspaces/by-key/WAT",
        status_code=404,
        code="not_found",
        message="workspace WAT not found",
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


def test_workspace_use_rewrites_config(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
) -> None:
    """
    ``kb workspace use KAN`` validates the key and writes
    ``default_workspace`` into ``config.toml``.
    """
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body("KAN"))
    result = runner.invoke(app, ["workspace", "use", "KAN"])
    assert result.exit_code == 0, result.stderr
    assert "Default workspace" in result.stdout

    contents = (config_dir / "config.toml").read_text()
    assert 'default_workspace = "KAN"' in contents


def test_workspace_use_bogus_key_does_not_touch_config(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
) -> None:
    """
    When the server rejects the key the config file is left alone.
    """
    before = (config_dir / "config.toml").read_text()
    mock_api.error(
        "GET",
        "/workspaces/by-key/BOGUS",
        status_code=404,
        code="not_found",
        message="workspace BOGUS not found",
    )
    result = runner.invoke(app, ["workspace", "use", "BOGUS"])
    assert result.exit_code == 1
    assert (config_dir / "config.toml").read_text() == before


def test_workspace_current_reports_unset(
    config_dir: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    With no env var and no ``default_workspace`` in config,
    ``kb workspace current`` says so clearly.
    """
    del config_dir
    monkeypatch.delenv("KANBEROO_WORKSPACE", raising=False)
    result = runner.invoke(app, ["workspace", "current"])
    assert result.exit_code == 0, result.stderr
    assert "No default workspace" in result.stdout


def test_workspace_current_reports_env(
    config_dir: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    ``$KANBEROO_WORKSPACE`` wins over any config value.
    """
    del config_dir
    monkeypatch.setenv("KANBEROO_WORKSPACE", "FROM_ENV")
    result = runner.invoke(app, ["workspace", "current"])
    assert result.exit_code == 0, result.stderr
    assert "FROM_ENV" in result.stdout
    assert "env" in result.stdout


def test_workspace_current_reports_config(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    After ``kb workspace use`` writes the config, ``kb workspace current``
    reports it with source ``config``.
    """
    monkeypatch.delenv("KANBEROO_WORKSPACE", raising=False)
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body("KAN"))
    assert runner.invoke(app, ["workspace", "use", "KAN"]).exit_code == 0

    result = runner.invoke(app, ["workspace", "current"])
    assert result.exit_code == 0, result.stderr
    assert "KAN" in result.stdout
    assert "config" in result.stdout
    del config_dir


def test_story_list_uses_flag_over_env_and_config(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The ``--workspace`` flag wins over both ``$KANBEROO_WORKSPACE`` and
    ``default_workspace`` in config.
    """
    (config_dir / "config.toml").write_text(
        'api_url = "http://test.invalid"\n'
        'token = "kbr_test"\n'
        f'database_url = "sqlite:///{config_dir / "kanberoo.db"}"\n'
        'default_workspace = "FROM_CONFIG"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("KANBEROO_WORKSPACE", "FROM_ENV")
    mock_api.json(
        "GET",
        "/workspaces/by-key/KAN",
        body=_ws_body("KAN"),
    )
    mock_api.json(
        "GET",
        "/workspaces/00000000-0000-0000-0000-000000000KAN/stories",
        body={"items": [], "next_cursor": None},
    )
    result = runner.invoke(app, ["story", "list", "--workspace", "KAN"])
    assert result.exit_code == 0, result.stderr
    assert any(r.path == "/workspaces/by-key/KAN" for r in mock_api.requests)


def test_story_list_uses_env_over_config(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    ``$KANBEROO_WORKSPACE`` wins over ``default_workspace`` in config
    when the ``--workspace`` flag is omitted.
    """
    (config_dir / "config.toml").write_text(
        'api_url = "http://test.invalid"\n'
        'token = "kbr_test"\n'
        f'database_url = "sqlite:///{config_dir / "kanberoo.db"}"\n'
        'default_workspace = "FROM_CONFIG"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("KANBEROO_WORKSPACE", "ENVKEY")
    mock_api.json(
        "GET",
        "/workspaces/by-key/ENVKEY",
        body=_ws_body("ENVKEY"),
    )
    mock_api.json(
        "GET",
        "/workspaces/00000000-0000-0000-0000-000000ENVKEY/stories",
        body={"items": [], "next_cursor": None},
    )
    result = runner.invoke(app, ["story", "list"])
    assert result.exit_code == 0, result.stderr
    assert any(r.path == "/workspaces/by-key/ENVKEY" for r in mock_api.requests)


def test_story_list_falls_back_to_config(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    When no flag or env var is set, ``default_workspace`` in config is
    used.
    """
    (config_dir / "config.toml").write_text(
        'api_url = "http://test.invalid"\n'
        'token = "kbr_test"\n'
        f'database_url = "sqlite:///{config_dir / "kanberoo.db"}"\n'
        'default_workspace = "CFGKEY"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("KANBEROO_WORKSPACE", raising=False)
    mock_api.json(
        "GET",
        "/workspaces/by-key/CFGKEY",
        body=_ws_body("CFGKEY"),
    )
    mock_api.json(
        "GET",
        "/workspaces/00000000-0000-0000-0000-000000CFGKEY/stories",
        body={"items": [], "next_cursor": None},
    )
    result = runner.invoke(app, ["story", "list"])
    assert result.exit_code == 0, result.stderr
    assert any(r.path == "/workspaces/by-key/CFGKEY" for r in mock_api.requests)


def test_story_list_without_workspace_errors_cleanly(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    With no flag, env var, or config default the CLI exits 1 with a
    pointer to every resolution path.
    """
    del mock_api
    monkeypatch.delenv("KANBEROO_WORKSPACE", raising=False)
    # config_dir's default config.toml has no default_workspace.
    result = runner.invoke(app, ["story", "list"])
    assert result.exit_code == 1
    combined = result.stdout + result.stderr
    assert "no workspace specified" in combined.lower()
    assert "--workspace" in combined
    assert "KANBEROO_WORKSPACE" in combined
    del config_dir


def test_workspace_delete_by_key_with_yes_flag(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
) -> None:
    """
    ``workspace delete KAN --yes`` resolves by key, then issues the
    DELETE with the ETag from the prior GET and skips the prompt.
    """
    del config_dir
    ws = _ws_body("KAN")
    mock_api.json(
        "GET",
        "/workspaces/by-key/KAN",
        body=ws,
        headers={"etag": "1"},
    )
    mock_api.json(
        "GET",
        f"/workspaces/{ws['id']}",
        body=ws,
        headers={"etag": "1"},
    )

    def _delete(_request: Any) -> Any:
        import httpx

        return httpx.Response(204)

    mock_api.add("DELETE", f"/workspaces/{ws['id']}", _delete)
    result = runner.invoke(app, ["workspace", "delete", "KAN", "--yes"])
    assert result.exit_code == 0, result.stderr
    delete_reqs = [r for r in mock_api.requests if r.method == "DELETE"]
    assert delete_reqs
    assert delete_reqs[0].path == f"/workspaces/{ws['id']}"
    assert delete_reqs[0].headers["if-match"] == "1"
    assert "soft-deleted" in result.stdout.lower()


def test_workspace_delete_by_uuid_with_yes_flag(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
) -> None:
    """
    Passing the raw UUID short-circuits the by-key fallback but still
    lands at the same DELETE path.
    """
    del config_dir
    ws = _ws_body("KAN")
    mock_api.json(
        "GET",
        f"/workspaces/{ws['id']}",
        body=ws,
        headers={"etag": "1"},
    )

    def _delete(_request: Any) -> Any:
        import httpx

        return httpx.Response(204)

    mock_api.add("DELETE", f"/workspaces/{ws['id']}", _delete)
    result = runner.invoke(
        app,
        ["workspace", "delete", str(ws["id"]), "--yes"],
    )
    assert result.exit_code == 0, result.stderr
    delete_reqs = [r for r in mock_api.requests if r.method == "DELETE"]
    assert delete_reqs
    assert delete_reqs[0].path == f"/workspaces/{ws['id']}"


def test_workspace_delete_prompt_rejection_aborts(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
) -> None:
    """
    Answering 'n' to the confirm prompt exits cleanly (0) and never
    fires the DELETE request.
    """
    del config_dir
    ws = _ws_body("KAN")
    mock_api.json(
        "GET",
        "/workspaces/by-key/KAN",
        body=ws,
        headers={"etag": "1"},
    )
    result = runner.invoke(app, ["workspace", "delete", "KAN"], input="n\n")
    assert result.exit_code == 0
    assert "aborted" in result.stdout.lower()
    assert not any(r.method == "DELETE" for r in mock_api.requests)


def test_workspace_delete_not_found_exits_nonzero(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
) -> None:
    """
    A 404 from the resolver exits 1 with the server's error surfaced
    on stderr and no DELETE ever fired.
    """
    del config_dir
    mock_api.error(
        "GET",
        "/workspaces/by-key/WAT",
        status_code=404,
        code="not_found",
        message="workspace WAT not found",
    )
    result = runner.invoke(app, ["workspace", "delete", "WAT", "--yes"])
    assert result.exit_code == 1
    assert "not_found" in result.stderr
    assert not any(r.method == "DELETE" for r in mock_api.requests)
