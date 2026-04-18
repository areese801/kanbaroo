"""
Story-related MCP tools.

Stories are the most-used resource in the MCP surface. This module
exposes:

* ``list_stories``: paginated, filterable list.
* ``get_story``: single-story lookup by human id or UUID.
* ``create_story``: new story under a workspace.
* ``update_story``: patch everything except state.
* ``transition_story_state``: the dedicated state-machine mover.

The ``transition_story_state`` tool is separate from ``update_story``
because the REST API itself splits them: state changes go through
``POST /stories/{id}/transition`` so the service layer can stamp
``state_actor_type`` and enforce the state machine.
"""

from __future__ import annotations

from typing import Any

from kanberoo_mcp.client import McpApiClient
from kanberoo_mcp.concurrency import with_retry_on_412
from kanberoo_mcp.resolver import (
    epic_ref_to_id,
    looks_like_human_id,
    resolve_story,
    resolve_workspace,
)
from kanberoo_mcp.tools.base import ToolDef

_STORY_STATES = ["backlog", "todo", "in_progress", "in_review", "done"]
_STORY_PRIORITIES = ["none", "low", "medium", "high"]


def _list_stories(
    client: McpApiClient,
    args: dict[str, Any],
) -> dict[str, Any]:
    """
    Handler for ``list_stories``.
    """
    workspace = resolve_workspace(client, args["workspace"])
    params: dict[str, Any] = {}
    for src, dest in (
        ("state", "state"),
        ("priority", "priority"),
        ("tag", "tag"),
        ("cursor", "cursor"),
        ("limit", "limit"),
    ):
        if args.get(src) is not None:
            params[dest] = args[src]
    if args.get("epic") is not None:
        epic_ref = args["epic"]
        if looks_like_human_id(epic_ref):
            params["epic_id"] = epic_ref_to_id(client, epic_ref)
        else:
            params["epic_id"] = epic_ref
    response = client.get(
        f"/workspaces/{workspace['id']}/stories",
        params=params or None,
    )
    body: dict[str, Any] = response.json()
    return body


def _get_story(client: McpApiClient, args: dict[str, Any]) -> dict[str, Any]:
    """
    Handler for ``get_story``. Augments the story body with comments
    and linkages so the outer agent sees the whole picture in one
    call.
    """
    story = resolve_story(client, args["story"])
    story_id = story["id"]
    comments = client.get(f"/stories/{story_id}/comments").json()
    linkages = client.get(f"/stories/{story_id}/linkages").json()
    story["comments"] = comments.get("items", [])
    story["linkages"] = linkages.get("items", [])
    return story


def _create_story(client: McpApiClient, args: dict[str, Any]) -> dict[str, Any]:
    """
    Handler for ``create_story``. Resolves the workspace, resolves the
    optional epic reference (if the caller passed a human id or UUID),
    and POSTs the payload.
    """
    workspace = resolve_workspace(client, args["workspace"])
    payload: dict[str, Any] = {"title": args["title"]}
    if args.get("description") is not None:
        payload["description"] = args["description"]
    if args.get("priority") is not None:
        payload["priority"] = args["priority"]
    if args.get("epic") is not None:
        payload["epic_id"] = epic_ref_to_id(client, args["epic"])
    response = client.post(
        f"/workspaces/{workspace['id']}/stories",
        json=payload,
    )
    created: dict[str, Any] = response.json()
    return {"message": f"created story {created['human_id']}", "story": created}


def _update_story(client: McpApiClient, args: dict[str, Any]) -> dict[str, Any]:
    """
    Handler for ``update_story``. Uses the 412-retry helper so a race
    with a concurrent TUI edit self-heals once before surfacing.
    """
    story = resolve_story(client, args["story"])
    payload: dict[str, Any] = {}
    for key in (
        "title",
        "description",
        "priority",
        "branch_name",
        "commit_sha",
        "pr_url",
    ):
        if key in args and args[key] is not None:
            payload[key] = args[key]
    if args.get("epic") is not None:
        payload["epic_id"] = epic_ref_to_id(client, args["epic"])
    if not payload:
        return {"message": "no fields to update", "story": story}
    path = f"/stories/{story['id']}"

    def _patch(etag: str) -> Any:
        return client.patch(path, json=payload, headers={"If-Match": etag})

    response = with_retry_on_412(client, path, _patch)
    updated: dict[str, Any] = response.json()
    return {"message": f"updated story {updated['human_id']}", "story": updated}


def _transition_story(
    client: McpApiClient,
    args: dict[str, Any],
) -> dict[str, Any]:
    """
    Handler for ``transition_story_state``.
    """
    story = resolve_story(client, args["story"])
    payload: dict[str, Any] = {"to_state": args["to_state"]}
    if args.get("reason") is not None:
        payload["reason"] = args["reason"]
    entity_path = f"/stories/{story['id']}"
    action_path = f"/stories/{story['id']}/transition"

    def _post(etag: str) -> Any:
        return client.post(action_path, json=payload, headers={"If-Match": etag})

    response = with_retry_on_412(client, entity_path, _post)
    updated: dict[str, Any] = response.json()
    return {
        "message": (f"transitioned story {updated['human_id']} to {updated['state']}"),
        "story": updated,
    }


def build_story_tools() -> list[ToolDef]:
    """
    Return every story-scoped tool definition.
    """
    return [
        ToolDef(
            name="list_stories",
            description=(
                "Search and filter stories within a workspace. Use when "
                "asked about work status, to find stories by tag, or to "
                "scan a specific column of the board. Supports filters "
                "on state, priority, epic, and tag plus cursor "
                "pagination."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["workspace"],
                "properties": {
                    "workspace": {
                        "type": "string",
                        "description": "Workspace key or UUID.",
                    },
                    "state": {"type": "string", "enum": _STORY_STATES},
                    "priority": {
                        "type": "string",
                        "enum": _STORY_PRIORITIES,
                    },
                    "epic": {
                        "type": "string",
                        "description": ("Epic human id (KAN-N) or UUID to filter by."),
                    },
                    "tag": {
                        "type": "string",
                        "description": "Tag name to filter by.",
                    },
                    "cursor": {"type": "string"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                    },
                },
            },
            handler=_list_stories,
        ),
        ToolDef(
            name="get_story",
            description=(
                "Fetch a story including its comments and linkages. Use "
                "when the user names a story by its human id (KAN-1) or "
                "when you need the full context before commenting, "
                "transitioning, or linking."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["story"],
                "properties": {
                    "story": {
                        "type": "string",
                        "description": "Story human id (KAN-N) or UUID.",
                    }
                },
            },
            handler=_get_story,
        ),
        ToolDef(
            name="create_story",
            description=(
                "Create a new story under a workspace. Ask the user for "
                "the workspace and priority if they are ambiguous; "
                "stories start in the 'backlog' state. Mutations stamp "
                "actor_type=claude."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["workspace", "title"],
                "properties": {
                    "workspace": {
                        "type": "string",
                        "description": "Workspace key or UUID.",
                    },
                    "title": {"type": "string"},
                    "description": {
                        "type": "string",
                        "description": "Markdown body.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": _STORY_PRIORITIES,
                    },
                    "epic": {
                        "type": "string",
                        "description": ("Optional parent epic human id or UUID."),
                    },
                },
            },
            handler=_create_story,
        ),
        ToolDef(
            name="update_story",
            description=(
                "Patch a story's title, description, priority, epic, "
                "branch, commit, or PR url. Use for any field EXCEPT "
                "state (use transition_story_state for state changes). "
                "Mutations stamp actor_type=claude."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["story"],
                "properties": {
                    "story": {
                        "type": "string",
                        "description": "Story human id or UUID.",
                    },
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": _STORY_PRIORITIES,
                    },
                    "epic": {
                        "type": "string",
                        "description": "New parent epic (human id or UUID).",
                    },
                    "branch_name": {"type": "string"},
                    "commit_sha": {"type": "string"},
                    "pr_url": {"type": "string"},
                },
            },
            handler=_update_story,
        ),
        ToolDef(
            name="transition_story_state",
            description=(
                "Move a story through the kanban state machine "
                "(backlog, todo, in_progress, in_review, done). "
                "Mutations stamp actor_type=claude. Always confirm "
                "with the user before closing a story (moving to done)."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["story", "to_state"],
                "properties": {
                    "story": {
                        "type": "string",
                        "description": "Story human id or UUID.",
                    },
                    "to_state": {
                        "type": "string",
                        "enum": _STORY_STATES,
                    },
                    "reason": {
                        "type": "string",
                        "description": (
                            "Optional free-text note surfaced in the audit log."
                        ),
                    },
                },
            },
            handler=_transition_story,
        ),
    ]
