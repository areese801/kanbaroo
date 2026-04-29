"""
Tests for ``kb token``.
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

import httpx
from typer.testing import CliRunner

from kanbaroo_cli.app import app


def _token_body(
    *,
    token_id: str = "token-1",
    revoked: bool = False,
    plaintext: str | None = None,
) -> dict[str, Any]:
    """
    Canned token read body (with optional plaintext for the create path).
    """
    body: dict[str, Any] = {
        "id": token_id,
        "token_hash": "deadbeef",
        "actor_type": "human",
        "actor_id": "adam",
        "name": "personal",
        "created_at": "2026-04-18T00:00:00Z",
        "last_used_at": None,
        "revoked_at": "2026-04-18T00:00:00Z" if revoked else None,
    }
    if plaintext is not None:
        body["plaintext"] = plaintext
    return body


def test_token_list(mock_api: Any, config_dir: Path, runner: CliRunner) -> None:
    """
    ``kb token list`` renders every token.
    """
    del config_dir
    mock_api.json("GET", "/tokens", body=[_token_body()])
    result = runner.invoke(app, ["token", "list"])
    assert result.exit_code == 0, result.stderr
    assert "token-1" in result.stdout


def test_token_create(mock_api: Any, config_dir: Path, runner: CliRunner) -> None:
    """
    ``kb token create`` POSTs the actor info and surfaces the plaintext.
    """
    del config_dir
    mock_api.json(
        "POST",
        "/tokens",
        body=_token_body(plaintext="kbr_newtoken"),
        status_code=201,
    )
    result = runner.invoke(
        app,
        [
            "token",
            "create",
            "--name",
            "mcp",
            "--actor-type",
            "claude",
            "--actor-id",
            "outer-claude",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert "kbr_newtoken" in result.stdout
    assert mock_api.requests[-1].body == {
        "name": "mcp",
        "actor_type": "claude",
        "actor_id": "outer-claude",
    }


def test_token_create_output_file(
    mock_api: Any,
    config_dir: Path,
    runner: CliRunner,
    tmp_path: Path,
) -> None:
    """
    ``kb token create --output-file`` writes the plaintext to disk
    with mode 0600, a trailing newline, and creates parent dirs as
    needed.
    """
    del config_dir
    mock_api.json(
        "POST",
        "/tokens",
        body=_token_body(plaintext="kbr_outputfile"),
        status_code=201,
    )
    target = tmp_path / "tokens" / "claude-foo"
    result = runner.invoke(
        app,
        [
            "token",
            "create",
            "--name",
            "mcp",
            "--actor-type",
            "claude",
            "--actor-id",
            "claude-foo",
            "--output-file",
            str(target),
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert target.read_text(encoding="utf-8") == "kbr_outputfile\n"
    mode_bits = stat.S_IMODE(target.stat().st_mode)
    assert mode_bits == 0o600, oct(mode_bits)
    assert "kbr_outputfile" in result.stdout
    assert "written to" in result.stdout


def test_token_revoke(mock_api: Any, config_dir: Path, runner: CliRunner) -> None:
    """
    ``kb token revoke`` with ``--yes`` hits DELETE without a prompt.
    """
    del config_dir

    def _delete(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    mock_api.add("DELETE", "/tokens/token-1", _delete)
    result = runner.invoke(app, ["token", "revoke", "token-1", "--yes"])
    assert result.exit_code == 0, result.stderr
    assert any(r.path == "/tokens/token-1" for r in mock_api.requests)
