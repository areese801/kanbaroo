"""
Implementation of ``kb backup``.

Local-only command: reads the configured SQLite file path from the
CLI config (or ``$KANBEROO_DATABASE_URL``) and copies it to a
timestamped path under ``--output`` (default ``~/.kanberoo/backups``).
Does not touch the running server: snapshotting a SQLite file while
the writer is live is safe as long as readers see a consistent page
view, and using the filesystem here lets the command work even when
the server is offline.

Any database URL that is not SQLite (i.e. Postgres in a later phase)
causes the command to print a warning and exit with code 0. The
contract is "SQLite only for now"; we do not want to silently imply a
Postgres backup is happening.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import typer

from kanberoo_cli.config import default_config_dir
from kanberoo_cli.context import require_config
from kanberoo_cli.rendering import stderr_console, stdout_console

SQLITE_PREFIXES: tuple[str, ...] = ("sqlite:///", "sqlite+pysqlite:///")


def _sqlite_path_from_url(url: str) -> Path | None:
    """
    Return the file path embedded in a ``sqlite://`` URL, or ``None``
    if the URL does not point at a SQLite file.

    ``sqlite:///:memory:`` and other non-file forms return ``None``.
    """
    for prefix in SQLITE_PREFIXES:
        if url.startswith(prefix):
            raw = url[len(prefix) :]
            if not raw or raw == ":memory:":
                return None
            return Path(raw)
    return None


def backup_command(
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Directory to write the backup into. Default: ~/.kanberoo/backups.",
    ),
) -> None:
    """
    Copy the configured SQLite database file to a timestamped path.
    """
    config = require_config()
    src = _sqlite_path_from_url(config.database_url)
    if src is None:
        stderr_console.print(
            "[yellow]Warning:[/yellow] database_url is not a SQLite file URL; "
            "kb backup only supports SQLite in v1. Skipping."
        )
        raise typer.Exit(code=0)

    if not src.exists():
        stderr_console.print(f"[red]Error:[/red] database file {src} does not exist.")
        raise typer.Exit(code=1)

    dest_dir = output if output is not None else default_config_dir() / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"kanberoo-{timestamp}.db"
    shutil.copy2(src, dest)
    stdout_console.print(f"wrote [bold]{dest}[/bold].")
