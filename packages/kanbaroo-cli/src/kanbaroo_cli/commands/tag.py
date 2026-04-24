"""
Implementation of ``kb tag``.

Tags are workspace-scoped and do not participate in optimistic
concurrency, so rename and delete do not require ``If-Match``. The
commands mirror the REST surface in ``kanbaroo_api.routers.tags``.
"""

from __future__ import annotations

from typing import Any

import typer

from kanbaroo_cli.client import ApiError
from kanbaroo_cli.context import build_client, require_config
from kanbaroo_cli.rendering import (
    exit_on_api_error,
    print_json,
    print_table,
    stdout_console,
)
from kanbaroo_cli.resolvers import require_effective_workspace, resolve_workspace
from kanbaroo_cli.similar import fetch_similar_entities, print_similar_entities

app = typer.Typer(
    name="tag",
    help="Manage workspace-scoped tags.",
    no_args_is_help=True,
)


def _swatch_markup(color: str | None) -> str:
    """
    Build a Rich-markup color swatch for the ``color`` column.

    Renders a two-space background-coloured block followed by the hex
    text so the listing shows both the swatch and the raw value. Tags
    with no colour get a plain dash so the column never collapses to
    an empty cell.
    """
    if not color:
        return "-"
    return f"[on {color}]  [/]  {color}"


def _tag_row(item: dict[str, Any]) -> list[str]:
    """
    Format a single tag record into a :func:`print_table` row.

    Soft-deleted rows dim the ``name`` cell so they are obviously
    distinct from live tags when ``--include-deleted`` is active.
    """
    name = str(item["name"])
    is_deleted = bool(item["deleted_at"])
    name_cell = f"[dim]{name}[/dim]" if is_deleted else name
    return [
        name_cell,
        _swatch_markup(item["color"]),
        str(item["id"]),
        "yes" if is_deleted else "no",
    ]


@app.command("list")
def list_tags(
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        help=(
            "Workspace key or UUID. Falls back to $KANBAROO_WORKSPACE "
            "and default_workspace from config."
        ),
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

    Soft-deleted tags are hidden by default. When any exist a short
    hint points at ``--include-deleted`` so the CLI does not silently
    omit them.
    """
    config = require_config()
    workspace_ref = require_effective_workspace(workspace, config)
    with build_client(config) as client:
        try:
            ws = resolve_workspace(client, workspace_ref)
            # Always request the full set so we can count soft-deleted
            # tags without a second round-trip. Tag volume per
            # workspace is small (single-page), so the cost is nil.
            response = client.get(
                f"/workspaces/{ws['id']}/tags",
                params={"include_deleted": True},
            )
        except ApiError as exc:
            exit_on_api_error(exc)
        items = response.json()["items"]

    deleted_items = [item for item in items if item["deleted_at"]]
    displayed = (
        items if include_deleted else [item for item in items if not item["deleted_at"]]
    )

    if as_json:
        print_json(displayed)
        return
    rows = [_tag_row(item) for item in displayed]
    print_table(
        columns=["name", "color", "id", "deleted"],
        rows=rows,
        title=f"tags in {ws['key']}",
    )
    if not include_deleted and deleted_items:
        count = len(deleted_items)
        plural = "" if count == 1 else "s"
        stdout_console.print(
            f"[dim]Note: {count} soft-deleted tag{plural} not shown. "
            "Use --include-deleted to see them.[/dim]"
        )


@app.command("create")
def create_tag(
    name: str = typer.Argument(..., help="Tag name."),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        help=(
            "Workspace key or UUID. Falls back to $KANBAROO_WORKSPACE "
            "and default_workspace from config."
        ),
    ),
    color: str | None = typer.Option(
        None,
        "--color",
        help="Optional hex color (e.g. #cc3333).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Skip the duplicate-name prompt and create the tag regardless.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """
    Create a workspace-scoped tag.

    Mirrors ``kb story create``: a normalised-name check runs first
    so visually similar tags (``UI`` vs ``ui``) trigger an interactive
    confirmation. ``--force`` skips the prompt; ``--json`` never
    prompts but folds the matches into a ``warnings`` field.
    """
    config = require_config()
    workspace_ref = require_effective_workspace(workspace, config)
    payload: dict[str, Any] = {"name": name}
    if color is not None:
        payload["color"] = color
    similar: list[dict[str, Any]] = []
    with build_client(config) as client:
        try:
            ws = resolve_workspace(client, workspace_ref)
            similar = fetch_similar_entities(
                client,
                workspace_id=str(ws["id"]),
                resource="tags",
                field_name="name",
                value=name,
            )
            if similar and not as_json and not force:
                print_similar_entities(similar, label_key="name", entity="tag")
                confirmed = typer.confirm("Create anyway?", default=False)
                if not confirmed:
                    stdout_console.print("aborted: existing entity has a similar name")
                    raise typer.Exit(code=1)
            response = client.post(
                f"/workspaces/{ws['id']}/tags",
                json=payload,
            )
        except ApiError as exc:
            exit_on_api_error(exc)
        body = response.json()

    if as_json:
        if similar:
            body = {**body, "warnings": {"similar": [s["id"] for s in similar]}}
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
