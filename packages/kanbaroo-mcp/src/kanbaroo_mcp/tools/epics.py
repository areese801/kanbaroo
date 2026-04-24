"""
Epic-related MCP tools.

* :func:`list_epics_tool`: list epics under a workspace.
* :func:`create_epic_tool`: create a new epic.
* :func:`update_epic_tool`: patch title/description/state (state=open
  or closed drives the close/reopen behaviour).

Convenience close/reopen endpoints (``POST /epics/{id}/close``) are
folded into ``update_epic`` by accepting ``state`` directly: the outer
agent does not need to remember two different tools for what is
logically one decision.
"""

from __future__ import annotations

from typing import Any

from kanbaroo_mcp.client import McpApiClient
from kanbaroo_mcp.concurrency import with_retry_on_412
from kanbaroo_mcp.resolver import resolve_epic, resolve_workspace
from kanbaroo_mcp.tools.base import ToolDef

_ALLOWED_EPIC_STATES = ["open", "closed"]


def _list_epics(client: McpApiClient, args: dict[str, Any]) -> dict[str, Any]:
    """
    Handler for ``list_epics``.
    """
    workspace = resolve_workspace(client, args["workspace"])
    params: dict[str, Any] = {}
    if args.get("include_deleted"):
        params["include_deleted"] = "true"
    response = client.get(
        f"/workspaces/{workspace['id']}/epics",
        params=params or None,
    )
    body: dict[str, Any] = response.json()
    return body


def _create_epic(client: McpApiClient, args: dict[str, Any]) -> dict[str, Any]:
    """
    Handler for ``create_epic``.

    Always queries ``/workspaces/{id}/epics/similar`` first; the
    matches are returned in ``warnings.similar`` so the outer Claude
    can relay the warning to the user. Creation is never blocked
    here: the agent surfaces the concern, the user decides.
    """
    workspace = resolve_workspace(client, args["workspace"])
    title = args["title"]
    similar_response = client.get(
        f"/workspaces/{workspace['id']}/epics/similar",
        params={"title": title},
    )
    similar = list(similar_response.json().get("items", []))
    payload: dict[str, Any] = {"title": title}
    if args.get("description") is not None:
        payload["description"] = args["description"]
    response = client.post(
        f"/workspaces/{workspace['id']}/epics",
        json=payload,
    )
    created: dict[str, Any] = response.json()
    result: dict[str, Any] = {
        "message": f"created epic {created['human_id']}",
        "epic": created,
    }
    if similar:
        result["warnings"] = {"similar": similar}
    return result


def _update_epic(client: McpApiClient, args: dict[str, Any]) -> dict[str, Any]:
    """
    Handler for ``update_epic``.
    """
    epic = resolve_epic(client, args["epic"])
    payload: dict[str, Any] = {}
    for field_name in ("title", "description", "state"):
        if field_name in args and args[field_name] is not None:
            payload[field_name] = args[field_name]
    if not payload:
        return {"message": "no fields to update", "epic": epic}
    path = f"/epics/{epic['id']}"

    def _patch(etag: str) -> Any:
        return client.patch(path, json=payload, headers={"If-Match": etag})

    response = with_retry_on_412(client, path, _patch)
    updated: dict[str, Any] = response.json()
    return {"message": f"updated epic {updated['human_id']}", "epic": updated}


def build_epic_tools() -> list[ToolDef]:
    """
    Return every epic-scoped tool definition.
    """
    return [
        ToolDef(
            name="list_epics",
            description=(
                "List epics under a workspace. Use to discover existing "
                "epics when the user wants to group a new story under one."
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
                    "include_deleted": {
                        "type": "boolean",
                        "description": ("Include soft-deleted epics. Default false."),
                    },
                },
            },
            handler=_list_epics,
        ),
        ToolDef(
            name="create_epic",
            description=(
                "Create a new epic under a workspace. Use when the user "
                "wants a container for a set of related stories. The "
                "epic is created in state 'open'."
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
                },
            },
            handler=_create_epic,
        ),
        ToolDef(
            name="update_epic",
            description=(
                "Patch an epic's title, description, or state. Pass "
                "state='closed' to close the epic or state='open' to "
                "reopen it. Mutations stamp actor_type=claude."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["epic"],
                "properties": {
                    "epic": {
                        "type": "string",
                        "description": "Epic human id (KAN-N) or UUID.",
                    },
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "state": {
                        "type": "string",
                        "enum": _ALLOWED_EPIC_STATES,
                    },
                },
            },
            handler=_update_epic,
        ),
    ]
