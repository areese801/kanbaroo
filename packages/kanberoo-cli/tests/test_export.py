"""
Tests for ``kb export``.

The streaming/write path is exercised against a tiny canned archive
bytestring; the 404 path asserts the CLI prints a clean "not available
yet" message rather than a traceback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from kanberoo_cli.app import app


def _ws_body() -> dict[str, Any]:
    """
    Canned workspace body for export tests.
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


def test_export_writes_archive_to_output(
    mock_api: Any, config_dir: Path, runner: CliRunner, tmp_path: Path
) -> None:
    """
    When the server returns a binary archive the CLI writes it to
    ``<output>/<key>-<timestamp>.tar.gz``.
    """
    del config_dir
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.bytes(
        "GET",
        "/workspaces/ws-kan/export",
        content=b"PK\x03\x04fake-tarball",
    )
    out = tmp_path / "snap"
    result = runner.invoke(
        app,
        ["export", "--workspace", "KAN", "--output", str(out)],
    )
    assert result.exit_code == 0, result.stderr
    produced = list(out.glob("KAN-*.tar.gz"))
    assert len(produced) == 1
    assert produced[0].read_bytes() == b"PK\x03\x04fake-tarball"


def test_export_404_prints_clear_message(
    mock_api: Any, config_dir: Path, runner: CliRunner, tmp_path: Path
) -> None:
    """
    A 404 from the server (endpoint not yet implemented) surfaces a
    "not available yet" message on stderr, not a traceback.
    """
    del config_dir
    mock_api.json("GET", "/workspaces/by-key/KAN", body=_ws_body())
    mock_api.error(
        "GET",
        "/workspaces/ws-kan/export",
        status_code=404,
        code="not_found",
        message="export endpoint not implemented",
    )
    out = tmp_path / "snap"
    result = runner.invoke(
        app,
        ["export", "--workspace", "KAN", "--output", str(out)],
    )
    assert result.exit_code == 1
    assert "not available yet" in result.stderr
