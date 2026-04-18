"""
Workspace-related MCP tools.

* :func:`list_workspaces_tool` exposes ``list_workspaces``.
* :func:`get_workspace_tool` exposes ``get_workspace``.

Neither tool mutates state; both map directly onto
``GET /workspaces`` and ``GET /workspaces/{key_or_id}`` respectively,
with the workspace-key resolver handling the common case where the
outer Claude passes a short key (``KAN``) rather than a UUID.
"""

from __future__ import annotations

from typing import Any

from kanberoo_mcp.client import McpApiClient
from kanberoo_mcp.resolver import resolve_workspace
from kanberoo_mcp.tools.base import ToolDef


def _list_workspaces(
    client: McpApiClient,
    args: dict[str, Any],
) -> dict[str, Any]:
    """
    Handler for ``list_workspaces``.
    """
    params: dict[str, Any] = {}
    if "limit" in args and args["limit"] is not None:
        params["limit"] = args["limit"]
    if "cursor" in args and args["cursor"] is not None:
        params["cursor"] = args["cursor"]
    response = client.get("/workspaces", params=params or None)
    body: dict[str, Any] = response.json()
    return body


def _get_workspace(
    client: McpApiClient,
    args: dict[str, Any],
) -> dict[str, Any]:
    """
    Handler for ``get_workspace``.
    """
    return resolve_workspace(client, args["workspace"])


def build_workspace_tools() -> list[ToolDef]:
    """
    Return every workspace-scoped tool definition.
    """
    return [
        ToolDef(
            name="list_workspaces",
            description=(
                "List available Kanberoo workspaces. Use this first to "
                "discover what workspaces exist before creating or "
                "looking up issues. Returns a paginated list; pass the "
                "returned 'next_cursor' back as 'cursor' to fetch more."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "description": "Maximum number of workspaces to return.",
                    },
                    "cursor": {
                        "type": "string",
                        "description": (
                            "Opaque pagination cursor returned by a previous call."
                        ),
                    },
                },
            },
            handler=_list_workspaces,
        ),
        ToolDef(
            name="get_workspace",
            description=(
                "Fetch a single workspace by short key (for example "
                "'KAN') or UUID. Use this when the user names a "
                "workspace and you need its id or metadata before "
                "making further calls."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["workspace"],
                "properties": {
                    "workspace": {
                        "type": "string",
                        "description": "Workspace key (e.g. 'KAN') or UUID.",
                    }
                },
            },
            handler=_get_workspace,
        ),
    ]
