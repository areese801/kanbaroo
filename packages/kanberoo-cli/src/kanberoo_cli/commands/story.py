"""
Implementation of ``kb story``.

Wraps every story-related REST endpoint the CLI exposes (list, create,
show, edit, move, comment, link, delete). All references to stories
and epics accept human ids (``KAN-123``) or UUIDs, translated via the
by-key endpoints.

``kb story edit`` follows the ``git commit`` pattern: dump the current
markdown body to a temp file, launch ``$EDITOR`` (default ``vim``),
read the file back, and submit a PATCH. An unchanged buffer short-
circuits without hitting the server.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import typer

from kanberoo_cli.client import ApiClient, ApiError
from kanberoo_cli.context import build_client, require_config
from kanberoo_cli.rendering import (
    exit_on_api_error,
    print_json,
    print_table,
    stdout_console,
)
from kanberoo_cli.resolvers import resolve_epic, resolve_story, resolve_workspace

app = typer.Typer(
    name="story",
    help="Create, inspect, and transition stories.",
    no_args_is_help=True,
)


def _story_rows(items: list[dict[str, Any]]) -> list[list[str]]:
    """
    Format a list of story bodies into table rows.
    """
    return [
        [
            str(item["human_id"]),
            str(item["title"]),
            str(item["state"]),
            str(item["priority"]),
            "yes" if item["deleted_at"] else "no",
        ]
        for item in items
    ]


def _resolve_epic_id(client: ApiClient, epic_ref: str | None) -> str | None:
    """
    Translate a ``--epic KAN-N`` flag into a UUID, or return ``None``
    when the flag was not supplied.
    """
    if epic_ref is None:
        return None
    epic = resolve_epic(client, epic_ref)
    return str(epic["id"])


@app.command("list")
def list_stories(
    workspace: str = typer.Option(
        ...,
        "--workspace",
        help="Workspace key or UUID.",
    ),
    state: str | None = typer.Option(
        None,
        "--state",
        help="Filter by state (backlog|todo|in_progress|in_review|done).",
    ),
    priority: str | None = typer.Option(
        None,
        "--priority",
        help="Filter by priority (none|low|medium|high).",
    ),
    epic: str | None = typer.Option(
        None,
        "--epic",
        help="Filter by epic (KAN-N or UUID).",
    ),
    tag: str | None = typer.Option(None, "--tag", help="Filter by tag name."),
    limit: int | None = typer.Option(
        None,
        "--limit",
        help="Maximum number of stories to return (default: all pages).",
    ),
    include_deleted: bool = typer.Option(
        False,
        "--include-deleted",
        help="Include soft-deleted stories in the listing.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON instead of a Rich table.",
    ),
) -> None:
    """
    List stories in a workspace with optional filters.
    """
    config = require_config()
    items: list[dict[str, Any]] = []
    with build_client(config) as client:
        try:
            ws = resolve_workspace(client, workspace)
            epic_id = _resolve_epic_id(client, epic)
            cursor: str | None = None
            while True:
                params: dict[str, Any] = {"limit": 200}
                if state is not None:
                    params["state"] = state
                if priority is not None:
                    params["priority"] = priority
                if epic_id is not None:
                    params["epic_id"] = epic_id
                if tag is not None:
                    params["tag"] = tag
                if include_deleted:
                    params["include_deleted"] = True
                if cursor is not None:
                    params["cursor"] = cursor
                response = client.get(
                    f"/workspaces/{ws['id']}/stories",
                    params=params,
                )
                body = response.json()
                items.extend(body["items"])
                cursor = body.get("next_cursor")
                if cursor is None or (limit is not None and len(items) >= limit):
                    break
            if limit is not None:
                items = items[:limit]
        except ApiError as exc:
            exit_on_api_error(exc)

    if as_json:
        print_json(items)
        return
    print_table(
        columns=["human_id", "title", "state", "priority", "deleted"],
        rows=_story_rows(items),
        title=f"stories in {ws['key']}",
    )


@app.command("create")
def create_story(
    workspace: str = typer.Option(..., "--workspace", help="Workspace key or UUID."),
    title: str = typer.Option(..., "--title", help="Story title."),
    description: str | None = typer.Option(
        None,
        "--description",
        help="Optional markdown description.",
    ),
    priority: str = typer.Option(
        "none",
        "--priority",
        help="Priority (none|low|medium|high). Defaults to none.",
    ),
    epic: str | None = typer.Option(
        None,
        "--epic",
        help="Associate the story with an epic (KAN-N or UUID).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """
    Create a new story.
    """
    config = require_config()
    with build_client(config) as client:
        try:
            ws = resolve_workspace(client, workspace)
            payload: dict[str, Any] = {
                "title": title,
                "priority": priority,
            }
            if description is not None:
                payload["description"] = description
            epic_id = _resolve_epic_id(client, epic)
            if epic_id is not None:
                payload["epic_id"] = epic_id
            response = client.post(
                f"/workspaces/{ws['id']}/stories",
                json=payload,
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
            ["priority", body["priority"]],
            ["id", body["id"]],
        ],
        title=f"created story {body['human_id']}",
    )


@app.command("show")
def show_story(
    ref: str = typer.Argument(..., help="Story handle (KAN-123) or UUID."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """
    Show a single story.
    """
    config = require_config()
    with build_client(config) as client:
        try:
            body = resolve_story(client, ref)
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
            ["priority", body["priority"]],
            ["epic_id", body["epic_id"] or ""],
            ["description", body["description"] or ""],
            ["id", body["id"]],
            ["version", str(body["version"])],
        ],
        title=f"story {body['human_id']}",
    )


def _launch_editor(initial_text: str) -> str:
    """
    Launch ``$EDITOR`` on a temp markdown file and return the edited
    contents.

    The default editor is ``vim``. Tests point ``$EDITOR`` at
    ``/bin/true`` so the subprocess is a cheap no-op; the buffer then
    matches ``initial_text`` and the caller short-circuits without a
    PATCH.
    """
    editor = os.environ.get("EDITOR", "vim")
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".md",
        delete=False,
        encoding="utf-8",
    ) as fh:
        fh.write(initial_text)
        temp_path = Path(fh.name)
    try:
        subprocess.run([editor, str(temp_path)], check=True)
        return temp_path.read_text(encoding="utf-8")
    finally:
        temp_path.unlink(missing_ok=True)


@app.command("edit")
def edit_story(
    ref: str = typer.Argument(..., help="Story handle (KAN-123) or UUID."),
) -> None:
    """
    Edit a story's description in ``$EDITOR``.

    Writes the current markdown body to a temp file, launches the
    editor, and submits a PATCH with the new body if anything changed.
    Exiting the editor without saving short-circuits with a friendly
    "no changes, nothing to do." on stdout.
    """
    config = require_config()
    with build_client(config) as client:
        try:
            story = resolve_story(client, ref)
            original = story["description"] or ""
            edited = _launch_editor(original)
            if edited == original:
                stdout_console.print("no changes, nothing to do.")
                return
            response = client.patch_with_etag(
                f"/stories/{story['id']}",
                json={"description": edited},
            )
        except ApiError as exc:
            exit_on_api_error(exc)
        body = response.json()

    stdout_console.print(
        f"updated [bold]{body['human_id']}[/bold] (version {body['version']})"
    )


@app.command("move")
def move_story(
    ref: str = typer.Argument(..., help="Story handle (KAN-123) or UUID."),
    to_state: str = typer.Argument(..., help="Target state."),
    reason: str | None = typer.Option(
        None,
        "--reason",
        help="Optional free-text reason recorded in the audit log.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """
    Transition a story into a new state.
    """
    config = require_config()
    payload: dict[str, Any] = {"to_state": to_state}
    if reason is not None:
        payload["reason"] = reason
    with build_client(config) as client:
        try:
            story = resolve_story(client, ref)
            response = client.post_with_etag(
                f"/stories/{story['id']}",
                f"/stories/{story['id']}/transition",
                json=payload,
            )
        except ApiError as exc:
            exit_on_api_error(exc)
        body = response.json()

    if as_json:
        print_json(body)
        return
    stdout_console.print(
        f"moved [bold]{body['human_id']}[/bold] to "
        f"[green]{body['state']}[/green] "
        f"(version {body['version']})"
    )


@app.command("comment")
def comment_story(
    ref: str = typer.Argument(..., help="Story handle (KAN-123) or UUID."),
    body_text: str = typer.Argument(..., help="Comment body (markdown)."),
    parent: str | None = typer.Option(
        None,
        "--parent",
        help="Reply to an existing comment UUID (single level).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """
    Post a comment on a story (or reply to an existing comment).
    """
    config = require_config()
    payload: dict[str, Any] = {"body": body_text}
    if parent is not None:
        payload["parent_id"] = parent
    with build_client(config) as client:
        try:
            story = resolve_story(client, ref)
            response = client.post(
                f"/stories/{story['id']}/comments",
                json=payload,
            )
        except ApiError as exc:
            exit_on_api_error(exc)
        body = response.json()

    if as_json:
        print_json(body)
        return
    stdout_console.print(
        f"commented on [bold]{story['human_id']}[/bold] (comment {body['id']})"
    )


@app.command("link")
def link_story(
    source: str = typer.Argument(..., help="Source story handle or UUID."),
    link_type: str = typer.Argument(
        ...,
        help="Link type (relates_to|blocks|is_blocked_by|duplicates|is_duplicated_by).",
    ),
    target: str = typer.Argument(..., help="Target story handle or UUID."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """
    Create a typed linkage between two stories.
    """
    config = require_config()
    with build_client(config) as client:
        try:
            src = resolve_story(client, source)
            tgt = resolve_story(client, target)
            payload: dict[str, Any] = {
                "source_type": "story",
                "source_id": src["id"],
                "target_type": "story",
                "target_id": tgt["id"],
                "link_type": link_type,
            }
            response = client.post("/linkages", json=payload)
        except ApiError as exc:
            exit_on_api_error(exc)
        body = response.json()

    if as_json:
        print_json(body)
        return
    stdout_console.print(
        f"linked [bold]{src['human_id']}[/bold] "
        f"[cyan]{link_type}[/cyan] "
        f"[bold]{tgt['human_id']}[/bold] "
        f"(linkage {body['id']})"
    )


@app.command("delete")
def delete_story(
    ref: str = typer.Argument(..., help="Story handle (KAN-123) or UUID."),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Skip the confirmation prompt.",
    ),
) -> None:
    """
    Soft-delete a story. Prompts for confirmation unless ``--yes``.
    """
    config = require_config()
    with build_client(config) as client:
        try:
            story = resolve_story(client, ref)
        except ApiError as exc:
            exit_on_api_error(exc)
        if not yes:
            confirmed = typer.confirm(
                f"Soft-delete story {story['human_id']} ({story['title']!r})?"
            )
            if not confirmed:
                stdout_console.print("aborted.")
                raise typer.Exit(code=0)
        try:
            client.delete_with_etag(f"/stories/{story['id']}")
        except ApiError as exc:
            exit_on_api_error(exc)

    stdout_console.print(f"soft-deleted [bold]{story['human_id']}[/bold].")
