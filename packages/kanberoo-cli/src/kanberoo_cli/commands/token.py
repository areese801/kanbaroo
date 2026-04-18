"""
Implementation of ``kb token``.

Wraps the ``/tokens`` REST surface. The create endpoint returns the
plaintext token exactly once; we surface it prominently and warn the
user to save it.
"""

from __future__ import annotations

from typing import Any

import typer

from kanberoo_cli.client import ApiError
from kanberoo_cli.context import build_client, require_config
from kanberoo_cli.rendering import (
    exit_on_api_error,
    print_json,
    print_table,
    stdout_console,
)

app = typer.Typer(
    name="token",
    help="Manage Kanberoo API tokens.",
    no_args_is_help=True,
)


@app.command("list")
def list_tokens(
    include_revoked: bool = typer.Option(
        False,
        "--include-revoked",
        help="Include revoked tokens in the listing.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """
    List every API token. Plaintext is never returned; only the hash
    prefix is surfaced so operators can identify tokens without seeing
    secrets.
    """
    config = require_config()
    with build_client(config) as client:
        try:
            params: dict[str, Any] = {}
            if include_revoked:
                params["include_revoked"] = True
            response = client.get("/tokens", params=params or None)
        except ApiError as exc:
            exit_on_api_error(exc)
        items = response.json()

    if as_json:
        print_json(items)
        return
    rows = [
        [
            str(item["id"]),
            str(item["name"]),
            f"{item['actor_type']}/{item['actor_id']}",
            str(item["created_at"]),
            "yes" if item["revoked_at"] else "no",
        ]
        for item in items
    ]
    print_table(
        columns=["id", "name", "actor", "created_at", "revoked"],
        rows=rows,
        title="api tokens",
    )


@app.command("create")
def create_token(
    name: str = typer.Option(..., "--name", help="Human-readable token label."),
    actor_type: str = typer.Option(
        ...,
        "--actor-type",
        help="Actor type (human|claude|system).",
    ),
    actor_id: str = typer.Option(
        ...,
        "--actor-id",
        help="Actor id (free-form label, e.g. 'outer-claude').",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """
    Issue a new API token. The plaintext is returned exactly once;
    save it before leaving this command.
    """
    config = require_config()
    payload: dict[str, Any] = {
        "name": name,
        "actor_type": actor_type,
        "actor_id": actor_id,
    }
    with build_client(config) as client:
        try:
            response = client.post("/tokens", json=payload)
        except ApiError as exc:
            exit_on_api_error(exc)
        body = response.json()

    if as_json:
        print_json(body)
        return
    stdout_console.print(
        "[bold yellow]Save this token now. It will not be shown again.[/bold yellow]"
    )
    print_table(
        columns=["field", "value"],
        rows=[
            ["plaintext", body["plaintext"]],
            ["id", body["id"]],
            ["name", body["name"]],
            ["actor_type", body["actor_type"]],
            ["actor_id", body["actor_id"]],
        ],
        title=f"created token {body['name']}",
    )


@app.command("revoke")
def revoke_token(
    token_id: str = typer.Argument(..., help="Token UUID."),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Skip the confirmation prompt.",
    ),
) -> None:
    """
    Revoke a token. Idempotent against already-revoked rows.
    """
    if not yes:
        confirmed = typer.confirm(f"Revoke token {token_id}?")
        if not confirmed:
            stdout_console.print("aborted.")
            raise typer.Exit(code=0)
    config = require_config()
    with build_client(config) as client:
        try:
            client.delete(f"/tokens/{token_id}")
        except ApiError as exc:
            exit_on_api_error(exc)
    stdout_console.print(f"revoked token [bold]{token_id}[/bold].")
