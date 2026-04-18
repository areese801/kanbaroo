"""
Shared rendering helpers for CLI commands.

Every list/show command supports ``--json`` for scripting and defaults
to a Rich-rendered table. Keeping the two rendering paths in one place
means individual commands only choose *what* to display, not *how*.
"""

from __future__ import annotations

import json as _json
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from kanberoo_cli.client import ApiError, ApiRequestError

stdout_console = Console()
stderr_console = Console(stderr=True)


def print_json(payload: Any) -> None:
    """
    Emit ``payload`` as compact JSON on stdout.

    Uses :func:`json.dumps` directly (rather than Rich's
    ``print_json``) so the output is deterministic and pipe-friendly.
    """
    stdout_console.print_json(_json.dumps(payload))


def print_table(
    *,
    columns: list[str],
    rows: list[list[str]],
    title: str | None = None,
) -> None:
    """
    Render a Rich table with the given columns and rows on stdout.

    Empty ``rows`` renders the header with a single "(none)" cell so
    the user never sees a blank box.
    """
    table = Table(title=title, show_lines=False)
    for col in columns:
        table.add_column(col)
    if not rows:
        table.add_row(*["(none)"] + [""] * (len(columns) - 1))
    else:
        for row in rows:
            table.add_row(*row)
    stdout_console.print(table)


def render_api_error(exc: ApiError) -> None:
    """
    Print a friendly error message for an API failure on stderr.

    Wraps both transport errors (server unreachable) and HTTP errors
    (canonical envelope) so command handlers can call this once and
    raise :class:`typer.Exit` immediately after.
    """
    if isinstance(exc, ApiRequestError):
        stderr_console.print(
            f"[red]Error ({exc.status_code} {exc.code}):[/red] {exc.message}"
        )
        if exc.details:
            stderr_console.print(f"[dim]details:[/dim] {exc.details}")
    else:
        stderr_console.print(f"[red]Error:[/red] {exc}")


def exit_on_api_error(exc: ApiError) -> None:
    """
    Render the error and raise :class:`typer.Exit` with code 1.

    Used by every command handler so the exit-code contract is
    identical across the CLI surface.
    """
    render_api_error(exc)
    raise typer.Exit(code=1) from exc
