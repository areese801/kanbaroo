"""
Implementation of ``kb workspace``.

Wraps the workspace REST surface. ``show`` takes either a UUID or a
short key (``KAN``) and falls back to a list scan when the first lookup
returns 404, so the user can address workspaces the same way they do
in the rest of the CLI.
"""

from __future__ import annotations

import typer

from kanberoo_cli.client import ApiError, ApiRequestError
from kanberoo_cli.context import build_client, require_config
from kanberoo_cli.rendering import exit_on_api_error, print_json, print_table
from kanberoo_cli.resolvers import resolve_workspace

app = typer.Typer(
    name="workspace",
    help="Create, list, and inspect workspaces.",
    no_args_is_help=True,
)


@app.command("list")
def list_workspaces(
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON instead of a Rich table.",
    ),
    include_deleted: bool = typer.Option(
        False,
        "--include-deleted",
        help="Include soft-deleted workspaces in the listing.",
    ),
) -> None:
    """
    List every workspace. Walks the paginated endpoint to collect the
    entire set in one command.
    """
    config = require_config()
    items: list[dict[str, object]] = []
    cursor: str | None = None
    with build_client(config) as client:
        try:
            while True:
                params: dict[str, object] = {"limit": 200}
                if include_deleted:
                    params["include_deleted"] = True
                if cursor is not None:
                    params["cursor"] = cursor
                response = client.get("/workspaces", params=params)
                body = response.json()
                items.extend(body["items"])
                cursor = body.get("next_cursor")
                if cursor is None:
                    break
        except ApiError as exc:
            exit_on_api_error(exc)

    if as_json:
        print_json(items)
        return

    rows = [
        [
            str(item["key"]),
            str(item["name"]),
            str(item["id"]),
            str(item["next_issue_num"]),
            "yes" if item["deleted_at"] else "no",
        ]
        for item in items
    ]
    print_table(
        columns=["key", "name", "id", "next_issue", "deleted"],
        rows=rows,
        title="workspaces",
    )


@app.command("create")
def create_workspace(
    key: str = typer.Option(..., "--key", help="Short prefix, e.g. KAN."),
    name: str = typer.Option(..., "--name", help="Human-readable workspace name."),
    description: str | None = typer.Option(
        None,
        "--description",
        help="Optional markdown description.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit the created workspace as JSON instead of a Rich panel.",
    ),
) -> None:
    """
    Create a new workspace.
    """
    config = require_config()
    payload: dict[str, object] = {"key": key, "name": name}
    if description is not None:
        payload["description"] = description
    with build_client(config) as client:
        try:
            response = client.post("/workspaces", json=payload)
        except ApiError as exc:
            exit_on_api_error(exc)
        body = response.json()

    if as_json:
        print_json(body)
        return
    print_table(
        columns=["field", "value"],
        rows=[
            ["id", body["id"]],
            ["key", body["key"]],
            ["name", body["name"]],
            ["description", body["description"] or ""],
        ],
        title=f"created workspace {body['key']}",
    )


@app.command("show")
def show_workspace(
    key_or_id: str = typer.Argument(..., help="Workspace key (KAN) or UUID."),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit the workspace body as JSON instead of a Rich table.",
    ),
) -> None:
    """
    Show a single workspace by its short key or UUID.
    """
    config = require_config()
    with build_client(config) as client:
        try:
            body = resolve_workspace(client, key_or_id)
        except ApiRequestError as exc:
            exit_on_api_error(exc)
        except ApiError as exc:
            exit_on_api_error(exc)

    if as_json:
        print_json(body)
        return
    print_table(
        columns=["field", "value"],
        rows=[
            ["id", body["id"]],
            ["key", body["key"]],
            ["name", body["name"]],
            ["description", body["description"] or ""],
            ["next_issue_num", str(body["next_issue_num"])],
            ["version", str(body["version"])],
            ["created_at", body["created_at"]],
            ["updated_at", body["updated_at"]],
            ["deleted_at", body["deleted_at"] or ""],
        ],
        title=f"workspace {body['key']}",
    )
