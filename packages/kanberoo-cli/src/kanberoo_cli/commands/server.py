"""
Implementation of ``kb server``.

Thin wrappers around ``docker compose up -d`` and ``docker compose
down``. ``--wait`` on ``start`` polls ``/api/v1/workspaces`` until the
server responds or 30 seconds elapse.

We shell out via :func:`subprocess.run` rather than importing a
docker-compose Python binding because the binding surface is messy and
users already have ``docker compose`` on PATH as the supported entry
point per ``docker-compose.yml`` at the project root. When
``$KANBEROO_COMPOSE_FILE`` is set we pass ``-f`` so the caller can
target a non-default file (useful for CI).
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any

import httpx
import typer

from kanberoo_cli.client import API_PREFIX
from kanberoo_cli.context import require_config
from kanberoo_cli.rendering import stderr_console, stdout_console

app = typer.Typer(
    name="server",
    help="Start or stop the Kanberoo API server via docker compose.",
    no_args_is_help=True,
)

_READY_TIMEOUT_SECONDS = 30.0
_READY_POLL_SECONDS = 0.5


def _compose_command(subcommand: list[str]) -> list[str]:
    """
    Build the ``docker compose`` command line, injecting
    ``-f $KANBEROO_COMPOSE_FILE`` when the override is set.
    """
    argv: list[str] = ["docker", "compose"]
    compose_file = os.environ.get("KANBEROO_COMPOSE_FILE")
    if compose_file:
        argv.extend(["-f", compose_file])
    argv.extend(subcommand)
    return argv


def _run_compose(subcommand: list[str]) -> None:
    """
    Invoke docker compose with the given subcommand and check the
    result. Any non-zero exit propagates to the user.
    """
    subprocess.run(_compose_command(subcommand), check=True)


def _poll_until_ready(
    *,
    base_url: str,
    token: str,
    timeout_seconds: float = _READY_TIMEOUT_SECONDS,
) -> bool:
    """
    Poll ``GET {base_url}{API_PREFIX}/workspaces`` until it responds
    with a 2xx or ``timeout_seconds`` elapses.

    Returns ``True`` on success, ``False`` on timeout.
    """
    deadline = time.monotonic() + timeout_seconds
    headers: dict[str, Any] = {"Authorization": f"Bearer {token}"}
    url = f"{base_url.rstrip('/')}{API_PREFIX}/workspaces"
    with httpx.Client(timeout=2.0) as probe:
        while time.monotonic() < deadline:
            try:
                response = probe.get(url, headers=headers)
                if 200 <= response.status_code < 300:
                    return True
            except httpx.HTTPError:
                pass
            time.sleep(_READY_POLL_SECONDS)
    return False


@app.command("start")
def start_server(
    wait: bool = typer.Option(
        False,
        "--wait",
        help="Poll the API until it responds or 30 seconds elapse.",
    ),
) -> None:
    """
    Start the server (``docker compose up -d``).
    """
    try:
        _run_compose(["up", "-d"])
    except subprocess.CalledProcessError as exc:
        stderr_console.print(
            f"[red]Error:[/red] docker compose up failed (exit {exc.returncode})."
        )
        raise typer.Exit(code=exc.returncode) from exc

    if wait:
        config = require_config()
        if not _poll_until_ready(
            base_url=config.api_url,
            token=config.token,
        ):
            stderr_console.print(
                "[red]Error:[/red] server did not respond within 30 seconds."
            )
            raise typer.Exit(code=1)

    stdout_console.print("server started.")


@app.command("stop")
def stop_server() -> None:
    """
    Stop the server (``docker compose down``).
    """
    try:
        _run_compose(["down"])
    except subprocess.CalledProcessError as exc:
        stderr_console.print(
            f"[red]Error:[/red] docker compose down failed (exit {exc.returncode})."
        )
        raise typer.Exit(code=exc.returncode) from exc
    stdout_console.print("server stopped.")
