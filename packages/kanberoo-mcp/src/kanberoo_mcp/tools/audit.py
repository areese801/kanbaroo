"""
Audit-related MCP tools.

The spec (§4.2) defines ``GET /audit/entity/{entity_type}/{id}`` as
the per-entity history endpoint. The tool translates a friendly
``entity`` argument like ``"story/KAN-1"`` or ``"workspace/KAN"`` into
the ``(entity_type, entity_uuid)`` pair the REST surface expects.

Note: the audit router itself is not yet wired into the FastAPI app
(see the REST-side-gaps note in the PR description). The tool's
request shape is correct; once the router is added the tool works
without changes.
"""

from __future__ import annotations

from typing import Any

from kanberoo_mcp.client import McpApiClient, McpApiRequestError
from kanberoo_mcp.resolver import resolve_epic, resolve_story, resolve_workspace
from kanberoo_mcp.tools.base import ToolDef

_SUPPORTED_ENTITY_TYPES = ("story", "epic", "workspace")


def _resolve_entity_id(
    client: McpApiClient,
    entity_type: str,
    ref: str,
) -> str:
    """
    Translate a human reference into the entity UUID the audit
    endpoint expects.
    """
    if entity_type == "story":
        return str(resolve_story(client, ref)["id"])
    if entity_type == "epic":
        return str(resolve_epic(client, ref)["id"])
    if entity_type == "workspace":
        return str(resolve_workspace(client, ref)["id"])
    raise McpApiRequestError(
        status_code=400,
        code="validation_error",
        message=(
            f"unsupported audit entity_type {entity_type!r}; expected one "
            f"of {', '.join(_SUPPORTED_ENTITY_TYPES)}"
        ),
        details={"entity_type": entity_type},
    )


def _get_audit_trail(
    client: McpApiClient,
    args: dict[str, Any],
) -> dict[str, Any]:
    """
    Handler for ``get_audit_trail``.
    """
    raw = args["entity"]
    if "/" not in raw:
        raise McpApiRequestError(
            status_code=400,
            code="validation_error",
            message=(
                "entity must be of the form '{type}/{ref}' (for example 'story/KAN-1')"
            ),
            details={"entity": raw},
        )
    entity_type, ref = raw.split("/", 1)
    entity_id = _resolve_entity_id(client, entity_type, ref)
    response = client.get(f"/audit/entity/{entity_type}/{entity_id}")
    body: dict[str, Any] = response.json()
    return body


def build_audit_tools() -> list[ToolDef]:
    """
    Return every audit-scoped tool definition.
    """
    return [
        ToolDef(
            name="get_audit_trail",
            description=(
                "Read the history of mutations on a specific entity. "
                "Pass 'entity' as '{type}/{ref}' where type is one of "
                "story, epic, workspace and ref is the human id "
                "(KAN-1, KAN, ...) or UUID."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["entity"],
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": (
                            "'{type}/{ref}' form, e.g. 'story/KAN-1' or "
                            "'workspace/KAN'."
                        ),
                    }
                },
            },
            handler=_get_audit_trail,
        ),
    ]
