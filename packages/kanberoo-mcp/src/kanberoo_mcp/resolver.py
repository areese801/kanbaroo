"""
Human-id and key resolvers for the Kanberoo MCP server.

Outer Claude addresses entities by their human-friendly references:
workspaces by their short key (``KAN``) or UUID, stories and epics by
their ``{KEY}-{N}`` human identifier (``KAN-123``) or UUID. Every
resolver maps to the matching ``/by-key`` REST endpoint when the
reference looks like a key or human id, and to the direct UUID
endpoint otherwise.

Every resolver returns the canonical entity JSON body (not just a
UUID) so callers that already needed the full body avoid a second
round-trip. Callers that only need the id read ``body["id"]``.
"""

from __future__ import annotations

from typing import Any

from kanberoo_mcp.client import McpApiClient, McpApiRequestError


def looks_like_human_id(candidate: str) -> bool:
    """
    Return ``True`` if ``candidate`` is shaped like ``{KEY}-{N}``.
    """
    if "-" not in candidate:
        return False
    head, tail = candidate.rsplit("-", 1)
    return bool(head) and tail.isdigit()


def resolve_workspace(client: McpApiClient, key_or_id: str) -> dict[str, Any]:
    """
    Resolve a workspace by short key or UUID and return its full body.

    Workspace keys do not contain dashes (spec Appendix B and the
    conventional ``KAN``/``DATA`` shape), whereas UUIDs do. Treat any
    dashless reference as a key and route it straight to
    ``GET /workspaces/by-key/{key}``. Otherwise try the direct UUID
    endpoint first and fall back to the by-key endpoint for the rare
    hyphenated-key case. A 404 from the final lookup surfaces as
    :class:`McpApiRequestError` with ``code="not_found"``.
    """
    if "-" not in key_or_id:
        response = client.get(f"/workspaces/by-key/{key_or_id}")
        body: dict[str, Any] = response.json()
        return body

    try:
        response = client.get(f"/workspaces/{key_or_id}")
    except McpApiRequestError as exc:
        if exc.code != "not_found":
            raise
    else:
        direct: dict[str, Any] = response.json()
        return direct

    response = client.get(f"/workspaces/by-key/{key_or_id}")
    fallback: dict[str, Any] = response.json()
    return fallback


def resolve_story(client: McpApiClient, ref: str) -> dict[str, Any]:
    """
    Resolve a story by ``{KEY}-{N}`` human id or by UUID.

    Uses ``GET /stories/by-key/{ref}`` when ``ref`` matches the
    human-id pattern; otherwise treats ``ref`` as a UUID and calls
    ``GET /stories/{ref}``.
    """
    if looks_like_human_id(ref):
        response = client.get(f"/stories/by-key/{ref}")
    else:
        response = client.get(f"/stories/{ref}")
    body: dict[str, Any] = response.json()
    return body


def resolve_epic(client: McpApiClient, ref: str) -> dict[str, Any]:
    """
    Resolve an epic by ``{KEY}-{N}`` human id or by UUID.
    """
    if looks_like_human_id(ref):
        response = client.get(f"/epics/by-key/{ref}")
    else:
        response = client.get(f"/epics/{ref}")
    body: dict[str, Any] = response.json()
    return body


def resolve_tag_by_name(
    client: McpApiClient,
    *,
    workspace_id: str,
    tag_name: str,
) -> dict[str, Any]:
    """
    Resolve a tag by its human name within a workspace.

    Lists every tag in the workspace (tag volume per workspace is
    expected to stay small, per spec §3.3 / §4.2) and returns the
    first match on ``name``. Raises :class:`McpApiRequestError` with
    ``code="not_found"`` if no tag matches.
    """
    response = client.get(f"/workspaces/{workspace_id}/tags")
    page = response.json()
    for item in page.get("items", []):
        if item["name"] == tag_name:
            hit: dict[str, Any] = item
            return hit
    raise McpApiRequestError(
        status_code=404,
        code="not_found",
        message=f"tag {tag_name!r} not found in workspace {workspace_id!r}",
        details={"workspace_id": workspace_id, "tag_name": tag_name},
    )


def story_ref_to_id(client: McpApiClient, ref: str) -> str:
    """
    Convenience for callers that only need a story UUID.
    """
    return str(resolve_story(client, ref)["id"])


def epic_ref_to_id(client: McpApiClient, ref: str) -> str:
    """
    Convenience for callers that only need an epic UUID.
    """
    return str(resolve_epic(client, ref)["id"])
