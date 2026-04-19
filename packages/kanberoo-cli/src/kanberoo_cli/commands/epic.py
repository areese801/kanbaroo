"""
Implementation of ``kb epic``.

Wraps ``/workspaces/{id}/epics`` and the epic id-addressed endpoints.
``show``, ``close``, and ``reopen`` all accept a ``{KEY}-{N}`` handle
and translate via ``GET /epics/by-key/{human_id}`` (added this cage)
so the user never has to type a UUID.
"""

from __future__ import annotations

from typing import Any

import typer

from kanberoo_cli.client import ApiClient, ApiError, ApiRequestError
from kanberoo_cli.context import build_client, require_config
from kanberoo_cli.rendering import (
    exit_on_api_error,
    print_json,
    print_table,
    stderr_console,
    stdout_console,
)
from kanberoo_cli.resolvers import (
    require_effective_workspace,
    resolve_epic,
    resolve_workspace,
    try_resolve_other,
)
from kanberoo_cli.similar import fetch_similar_entities, print_similar_entities

app = typer.Typer(
    name="epic",
    help="Create, list, and transition epics.",
    no_args_is_help=True,
)


def _epic_rows(items: list[dict[str, object]]) -> list[list[str]]:
    """
    Format a list of epic bodies into table rows.
    """
    return [
        [
            str(item["human_id"]),
            str(item["title"]),
            str(item["state"]),
            "yes" if item["deleted_at"] else "no",
        ]
        for item in items
    ]


@app.command("list")
def list_epics(
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        help=(
            "Workspace key or UUID. Falls back to $KANBEROO_WORKSPACE "
            "and default_workspace from config."
        ),
    ),
    include_deleted: bool = typer.Option(
        False,
        "--include-deleted",
        help="Include soft-deleted epics in the listing.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON instead of a Rich table.",
    ),
) -> None:
    """
    List every epic in a workspace.
    """
    config = require_config()
    workspace_ref = require_effective_workspace(workspace, config)
    items: list[dict[str, object]] = []
    with build_client(config) as client:
        try:
            ws = resolve_workspace(client, workspace_ref)
            cursor: str | None = None
            while True:
                params: dict[str, object] = {"limit": 200}
                if include_deleted:
                    params["include_deleted"] = True
                if cursor is not None:
                    params["cursor"] = cursor
                response = client.get(
                    f"/workspaces/{ws['id']}/epics",
                    params=params,
                )
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
    print_table(
        columns=["human_id", "title", "state", "deleted"],
        rows=_epic_rows(items),
        title=f"epics in {ws['key']}",
    )


@app.command("create")
def create_epic(
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        help=(
            "Workspace key or UUID. Falls back to $KANBEROO_WORKSPACE "
            "and default_workspace from config."
        ),
    ),
    title: str = typer.Option(..., "--title", help="Epic title."),
    description: str | None = typer.Option(
        None,
        "--description",
        help="Optional markdown description.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Skip the duplicate-title prompt and create the epic regardless.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit the created epic as JSON instead of a Rich table.",
    ),
) -> None:
    """
    Create a new epic in ``workspace``.

    Mirrors ``kb story create``: a normalised-title check runs against
    the workspace before posting and warns the user about likely
    duplicates. ``--force`` skips the prompt; ``--json`` never prompts
    but folds the matches into a ``warnings`` field.
    """
    config = require_config()
    workspace_ref = require_effective_workspace(workspace, config)
    payload: dict[str, object] = {"title": title}
    if description is not None:
        payload["description"] = description
    similar: list[dict[str, Any]] = []
    with build_client(config) as client:
        try:
            ws = resolve_workspace(client, workspace_ref)
            similar = fetch_similar_entities(
                client,
                workspace_id=str(ws["id"]),
                resource="epics",
                field_name="title",
                value=title,
            )
            if similar and not as_json and not force:
                print_similar_entities(similar, label_key="human_id", entity="epic")
                confirmed = typer.confirm("Create anyway?", default=False)
                if not confirmed:
                    stdout_console.print("aborted: existing entity has a similar name")
                    raise typer.Exit(code=1)
            response = client.post(
                f"/workspaces/{ws['id']}/epics",
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
    print_table(
        columns=["field", "value"],
        rows=[
            ["human_id", body["human_id"]],
            ["title", body["title"]],
            ["state", body["state"]],
            ["id", body["id"]],
        ],
        title=f"created epic {body['human_id']}",
    )


@app.command("show")
def show_epic(
    ref: str = typer.Argument(..., help="Epic handle (e.g. KAN-4) or UUID."),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit the epic body as JSON instead of a Rich table.",
    ),
) -> None:
    """
    Show a single epic by its human id or UUID.

    A 404 from the epic lookup falls through to a story lookup with
    the same ref; if that hits, the user gets a hint to run
    ``kb story show`` instead of a bare "not found" message.
    """
    config = require_config()
    with build_client(config) as client:
        try:
            body = resolve_epic(client, ref)
        except ApiRequestError as exc:
            if exc.status_code == 404:
                _suggest_alternative(client, ref, missing="epic", alternative="story")
                raise typer.Exit(code=1) from exc
            exit_on_api_error(exc)
        except ApiError as exc:
            exit_on_api_error(exc)

    if as_json:
        print_json(body)
        return
    print_table(
        columns=["field", "value"],
        rows=[
            ["human_id", body["human_id"]],
            ["title", body["title"]],
            ["state", body["state"]],
            ["description", body["description"] or ""],
            ["id", body["id"]],
            ["version", str(body["version"])],
            ["created_at", body["created_at"]],
            ["updated_at", body["updated_at"]],
            ["deleted_at", body["deleted_at"] or ""],
        ],
        title=f"epic {body['human_id']}",
    )


def _transition(ref: str, action: str, *, as_json: bool) -> None:
    """
    Shared implementation of ``close`` and ``reopen``.

    Both endpoints require ``If-Match``; we fetch the epic first to
    learn its current version and then POST to the action path.
    """
    config = require_config()
    with build_client(config) as client:
        try:
            epic = resolve_epic(client, ref)
            response = client.post_with_etag(
                f"/epics/{epic['id']}",
                f"/epics/{epic['id']}/{action}",
            )
        except ApiError as exc:
            exit_on_api_error(exc)
        body = response.json()

    if as_json:
        print_json(body)
        return
    print_table(
        columns=["field", "value"],
        rows=[
            ["human_id", body["human_id"]],
            ["title", body["title"]],
            ["state", body["state"]],
            ["version", str(body["version"])],
        ],
        title=f"{action}d epic {body['human_id']}",
    )


@app.command("close")
def close_epic(
    ref: str = typer.Argument(..., help="Epic handle (e.g. KAN-4) or UUID."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """
    Close an epic.
    """
    _transition(ref, "close", as_json=as_json)


@app.command("reopen")
def reopen_epic(
    ref: str = typer.Argument(..., help="Epic handle (e.g. KAN-4) or UUID."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """
    Reopen a closed epic.
    """
    _transition(ref, "reopen", as_json=as_json)


def _suggest_alternative(
    client: ApiClient,
    ref: str,
    *,
    missing: str,
    alternative: str,
) -> None:
    """
    Print a Rich error explaining that ``ref`` is the other entity type.

    Mirrors the helper in ``kanberoo_cli.commands.story`` so both
    ``show`` commands offer the same "this looks like a story / epic"
    hint when the user picks the wrong one.
    """
    stderr_console.print(
        f"[red]Error (404 not_found):[/red] {missing} {ref!r} not found."
    )
    other = try_resolve_other(client, ref, other=alternative)
    if other is None:
        return
    handle = other.get("human_id", ref)
    stderr_console.print(
        f"{handle} is a {alternative} - try `kb {alternative} show {handle}`."
    )
