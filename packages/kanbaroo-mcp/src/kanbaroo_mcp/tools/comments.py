"""
Comment-related MCP tools.

Only one tool is exposed: ``comment_on_story``. Outer agents post
comments as part of their narration; reading comments happens as a
side-effect of ``get_story``. Editing or deleting comments is
deliberately not exposed: if an agent writes a bad comment the human
deletes it via the TUI.
"""

from __future__ import annotations

from typing import Any

from kanbaroo_mcp.client import McpApiClient
from kanbaroo_mcp.resolver import resolve_story
from kanbaroo_mcp.tools.base import ToolDef


def _comment_on_story(
    client: McpApiClient,
    args: dict[str, Any],
) -> dict[str, Any]:
    """
    Handler for ``comment_on_story``.
    """
    story = resolve_story(client, args["story"])
    payload: dict[str, Any] = {"body": args["body"]}
    if args.get("parent_comment_id") is not None:
        payload["parent_id"] = args["parent_comment_id"]
    response = client.post(
        f"/stories/{story['id']}/comments",
        json=payload,
    )
    created: dict[str, Any] = response.json()
    return {
        "message": f"posted comment on story {story['human_id']}",
        "comment": created,
    }


def build_comment_tools() -> list[ToolDef]:
    """
    Return every comment-scoped tool definition.
    """
    return [
        ToolDef(
            name="comment_on_story",
            description=(
                "Post a comment on a story or reply to an existing "
                "top-level comment. Threading is one level deep: "
                "replies to replies are rejected by the API. "
                "Mutations stamp actor_type=claude."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["story", "body"],
                "properties": {
                    "story": {
                        "type": "string",
                        "description": "Story human id (KAN-N) or UUID.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Markdown comment body.",
                    },
                    "parent_comment_id": {
                        "type": "string",
                        "description": (
                            "UUID of a top-level comment to reply to. "
                            "Omit for a top-level comment."
                        ),
                    },
                },
            },
            handler=_comment_on_story,
        ),
    ]
