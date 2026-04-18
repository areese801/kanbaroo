"""
Linkage-related MCP tools.

* ``link_stories``: create a typed linkage between two stories.
* ``unlink_stories``: soft-delete an existing linkage by id.

The API mirrors ``blocks`` / ``is_blocked_by`` and ``duplicates`` /
``is_duplicated_by`` automatically on both create and delete (spec
§3.1), so callers always pass a single source + target + link_type
and never both ends themselves.
"""

from __future__ import annotations

from typing import Any

from kanberoo_mcp.client import McpApiClient
from kanberoo_mcp.resolver import resolve_story
from kanberoo_mcp.tools.base import ToolDef

_LINK_TYPES = [
    "relates_to",
    "blocks",
    "is_blocked_by",
    "duplicates",
    "is_duplicated_by",
]


def _link_stories(
    client: McpApiClient,
    args: dict[str, Any],
) -> dict[str, Any]:
    """
    Handler for ``link_stories``.
    """
    source = resolve_story(client, args["source"])
    target = resolve_story(client, args["target"])
    payload: dict[str, Any] = {
        "source_type": "story",
        "source_id": source["id"],
        "target_type": "story",
        "target_id": target["id"],
        "link_type": args["link_type"],
    }
    response = client.post("/linkages", json=payload)
    created: dict[str, Any] = response.json()
    return {
        "message": (
            f"linked {source['human_id']} {args['link_type']} {target['human_id']}"
        ),
        "linkage": created,
    }


def _unlink_stories(
    client: McpApiClient,
    args: dict[str, Any],
) -> dict[str, Any]:
    """
    Handler for ``unlink_stories``.
    """
    linkage_id = args["linkage_id"]
    client.delete(f"/linkages/{linkage_id}")
    return {"message": f"unlinked linkage {linkage_id}", "linkage_id": linkage_id}


def build_linkage_tools() -> list[ToolDef]:
    """
    Return every linkage-scoped tool definition.
    """
    return [
        ToolDef(
            name="link_stories",
            description=(
                "Create a typed linkage between two stories. "
                "Supported types: relates_to, blocks, is_blocked_by, "
                "duplicates, is_duplicated_by. The 'blocks' and "
                "'duplicates' pairs auto-mirror: you only ever create "
                "one end."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["source", "target", "link_type"],
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Source story human id or UUID.",
                    },
                    "target": {
                        "type": "string",
                        "description": "Target story human id or UUID.",
                    },
                    "link_type": {"type": "string", "enum": _LINK_TYPES},
                },
            },
            handler=_link_stories,
        ),
        ToolDef(
            name="unlink_stories",
            description=(
                "Remove a linkage between two stories. The mirror row, "
                "if any (blocks/duplicates pairs), is soft-deleted in "
                "the same transaction. Pass the linkage UUID returned "
                "by link_stories or visible on a story's linkages list."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["linkage_id"],
                "properties": {
                    "linkage_id": {
                        "type": "string",
                        "description": "UUID of the linkage to remove.",
                    }
                },
            },
            handler=_unlink_stories,
        ),
    ]
