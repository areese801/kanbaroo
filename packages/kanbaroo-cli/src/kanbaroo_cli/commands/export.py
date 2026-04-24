"""
Implementation of ``kb export``.

Hits ``GET /api/v1/workspaces/{id}/export`` which is cage K's
responsibility. The CLI-side implementation here is correct in its
own right: resolve the workspace, stream the response body to
``<output>/<workspace_key>-<timestamp>.tar.gz``, and surface clear
errors when the endpoint is not yet available.

Until the export endpoint lands the server returns 404 (or another
canonical error envelope) and ``kb export`` prints a friendly
``export endpoint not available yet`` message instead of a traceback.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import typer

from kanbaroo_cli.client import ApiError, ApiRequestError, ApiTransportError
from kanbaroo_cli.context import build_client, require_config
from kanbaroo_cli.rendering import (
    exit_on_api_error,
    stderr_console,
    stdout_console,
)
from kanbaroo_cli.resolvers import require_effective_workspace, resolve_workspace


def export_command(
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        help=(
            "Workspace key or UUID. Falls back to $KANBAROO_WORKSPACE "
            "and default_workspace from config."
        ),
    ),
    output: Path = typer.Option(
        ...,
        "--output",
        help="Directory to write the exported archive into.",
    ),
) -> None:
    """
    Download a workspace export archive into ``output``.
    """
    config = require_config()
    workspace_ref = require_effective_workspace(workspace, config)
    output.mkdir(parents=True, exist_ok=True)
    with build_client(config) as client:
        try:
            ws = resolve_workspace(client, workspace_ref)
        except ApiError as exc:
            exit_on_api_error(exc)

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        dest = output / f"{ws['key']}-{timestamp}.tar.gz"
        try:
            response = client.get(f"/workspaces/{ws['id']}/export")
        except ApiRequestError as exc:
            if exc.status_code == 404:
                stderr_console.print(
                    "[red]Error:[/red] export endpoint not available yet. "
                    "This server does not expose /workspaces/{id}/export; "
                    "the feature arrives in a later milestone."
                )
                raise typer.Exit(code=1) from exc
            exit_on_api_error(exc)
        except ApiTransportError as exc:
            exit_on_api_error(exc)
        except httpx.HTTPError as exc:
            stderr_console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(code=1) from exc

        dest.write_bytes(response.content)

    stdout_console.print(f"wrote [bold]{dest}[/bold].")
