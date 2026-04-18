"""
Implementation of ``kb tag``.

Tags are workspace-scoped and do not participate in optimistic
concurrency, so rename and delete do not require ``If-Match``. The
commands mirror the REST surface in ``kanberoo_api.routers.tags``.
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
from kanberoo_cli.resolvers import resolve_workspace

app = typer.Typer(
    name="tag",
    help="Manage workspace-scoped tags.",
    no_args_is_help=True,
)


@app.command("list")
def list_tags(
    workspace: str = typer.Option(
        ...,
        "--workspace",
        help="Workspace key or UUID.",
    ),
    include_deleted: bool = typer.Option(
        False,
        "--include-deleted",
        help="Include soft-deleted tags in the listing.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """
    List every tag in a workspace.
    """
    config = require_config()
    with build_client(config) as client:
        try:
            ws = resolve_workspace(client, workspace)
            params: dict[str, Any] = {}
            if include_deleted:
                params["include_deleted"] = True
            response = client.get(
                f"/workspaces/{ws['id']}/tags",
                params=params or None,
            )
        except ApiError as exc:
            exit_on_api_error(exc)
        items = response.json()["items"]

    if as_json:
        print_json(items)
        return
    rows = [
        [
            str(item["name"]),
            str(item["color"] or ""),
            str(item["id"]),
            "yes" if item["deleted_at"] else "no",
        ]
        for item in items
    ]
    print_table(
        columns=["name", "color", "id", "deleted"],
        rows=rows,
        title=f"tags in {ws['key']}",
    )


@app.command("create")
def create_tag(
    name: str = typer.Argument(..., help="Tag name."),
    workspace: str = typer.Option(
        ...,
        "--workspace",
        help="Workspace key or UUID.",
    ),
    color: str | None = typer.Option(
        None,
        "--color",
        help="Optional hex color (e.g. #cc3333).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """
    Create a workspace-scoped tag.
    """
    config = require_config()
    payload: dict[str, Any] = {"name": name}
    if color is not None:
        payload["color"] = color
    with build_client(config) as client:
        try:
            ws = resolve_workspace(client, workspace)
            response = client.post(
                f"/workspaces/{ws['id']}/tags",
                json=payload,
            )
        except ApiError as exc:
            exit_on_api_error(exc)
        body = response.json()

    if as_json:
        print_json(body)
        return
    stdout_console.print(f"created tag [bold]{body['name']}[/bold] (id {body['id']})")


@app.command("rename")
def rename_tag(
    tag_id: str = typer.Argument(..., help="Tag UUID."),
    new_name: str = typer.Argument(..., help="New tag name."),
    color: str | None = typer.Option(
        None,
        "--color",
        help="Optionally recolor the tag at the same time.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """
    Rename and optionally recolor a tag.
    """
    config = require_config()
    payload: dict[str, Any] = {"name": new_name}
    if color is not None:
        payload["color"] = color
    with build_client(config) as client:
        try:
            response = client.patch(f"/tags/{tag_id}", json=payload)
        except ApiError as exc:
            exit_on_api_error(exc)
        body = response.json()

    if as_json:
        print_json(body)
        return
    stdout_console.print(f"renamed tag {tag_id} to [bold]{body['name']}[/bold]")


@app.command("delete")
def delete_tag(
    tag_id: str = typer.Argument(..., help="Tag UUID."),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Skip the confirmation prompt.",
    ),
) -> None:
    """
    Soft-delete a tag. Detaches the tag from every story that carried it.
    """
    if not yes:
        confirmed = typer.confirm(f"Soft-delete tag {tag_id}?")
        if not confirmed:
            stdout_console.print("aborted.")
            raise typer.Exit(code=0)
    config = require_config()
    with build_client(config) as client:
        try:
            client.delete(f"/tags/{tag_id}")
        except ApiError as exc:
            exit_on_api_error(exc)

    stdout_console.print(f"soft-deleted tag [bold]{tag_id}[/bold].")
