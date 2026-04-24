"""
Tag-related MCP tools.

The agent surface is intentionally narrow: list, add-by-name,
remove-by-name. Creating and deleting tags themselves is reserved for
humans (via the CLI or TUI); if the requested tag does not exist the
``add_tag_to_story`` tool raises ``not_found`` rather than silently
creating it, so the agent knows to ask the user.
"""

from __future__ import annotations

from typing import Any

from kanbaroo_mcp.client import McpApiClient, McpApiRequestError
from kanbaroo_mcp.resolver import resolve_story, resolve_tag_by_name, resolve_workspace
from kanbaroo_mcp.tools.base import ToolDef


def _list_tags(client: McpApiClient, args: dict[str, Any]) -> dict[str, Any]:
    """
    Handler for ``list_tags``.
    """
    workspace = resolve_workspace(client, args["workspace"])
    response = client.get(f"/workspaces/{workspace['id']}/tags")
    body: dict[str, Any] = response.json()
    return body


def _add_tag_to_story(
    client: McpApiClient,
    args: dict[str, Any],
) -> dict[str, Any]:
    """
    Handler for ``add_tag_to_story``.

    Resolves the story, looks up the tag by name within the story's
    workspace, and POSTs the association. Cross-workspace tagging is
    rejected by the API with 400 ``validation_error``; that bubbles up
    as-is.
    """
    story = resolve_story(client, args["story"])
    tag = resolve_tag_by_name(
        client,
        workspace_id=story["workspace_id"],
        tag_name=args["tag_name"],
    )
    response = client.post(
        f"/stories/{story['id']}/tags",
        json={"tag_ids": [tag["id"]]},
    )
    updated: dict[str, Any] = response.json()
    return {
        "message": (f"tagged {story['human_id']} with {args['tag_name']!r}"),
        "story": updated,
    }


def _remove_tag_from_story(
    client: McpApiClient,
    args: dict[str, Any],
) -> dict[str, Any]:
    """
    Handler for ``remove_tag_from_story``. Idempotent: removing a tag
    that is not associated is a silent no-op, matching the server's
    behaviour. If the tag name does not exist in the workspace at all
    we return a friendly confirmation rather than an error because the
    operation is conceptually a no-op anyway.
    """
    story = resolve_story(client, args["story"])
    try:
        tag = resolve_tag_by_name(
            client,
            workspace_id=story["workspace_id"],
            tag_name=args["tag_name"],
        )
    except McpApiRequestError as exc:
        if exc.code == "not_found":
            return {
                "message": (
                    f"tag {args['tag_name']!r} does not exist in "
                    f"workspace; nothing to remove"
                ),
                "story_id": story["id"],
            }
        raise
    client.delete(f"/stories/{story['id']}/tags/{tag['id']}")
    return {
        "message": (f"removed tag {args['tag_name']!r} from {story['human_id']}"),
        "story_id": story["id"],
    }


def build_tag_tools() -> list[ToolDef]:
    """
    Return every tag-scoped tool definition.
    """
    return [
        ToolDef(
            name="list_tags",
            description=(
                "List every tag defined in a workspace. Use before "
                "adding a tag to a story so you can confirm the tag "
                "already exists (agents should not create tags "
                "autonomously)."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["workspace"],
                "properties": {
                    "workspace": {
                        "type": "string",
                        "description": "Workspace key or UUID.",
                    }
                },
            },
            handler=_list_tags,
        ),
        ToolDef(
            name="add_tag_to_story",
            description=(
                "Attach an existing tag to a story by tag name. If the "
                "named tag does not exist in the workspace this tool "
                "returns 'not_found'; ask the user before creating new "
                "tags rather than doing it autonomously."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["story", "tag_name"],
                "properties": {
                    "story": {
                        "type": "string",
                        "description": "Story human id or UUID.",
                    },
                    "tag_name": {
                        "type": "string",
                        "description": "Existing tag name in the workspace.",
                    },
                },
            },
            handler=_add_tag_to_story,
        ),
        ToolDef(
            name="remove_tag_from_story",
            description=(
                "Remove a tag from a story by tag name. Idempotent: "
                "removing an unattached or unknown tag is a no-op."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["story", "tag_name"],
                "properties": {
                    "story": {
                        "type": "string",
                        "description": "Story human id or UUID.",
                    },
                    "tag_name": {"type": "string"},
                },
            },
            handler=_remove_tag_from_story,
        ),
    ]
