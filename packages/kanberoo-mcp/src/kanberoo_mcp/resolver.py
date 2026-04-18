"""
Human-id and key resolvers for the Kanberoo MCP server.

Outer Claude addresses entities by their human-friendly references:
workspaces by their short key (``KAN``) or UUID, stories and epics by
their ``{KEY}-{N}`` human identifier (``KAN-123``) or UUID. The REST
API serves by-key lookups for stories and epics directly; for
workspaces we fall back to scanning the workspace list because no
by-key endpoint exists yet (noted in task_complete as a REST-side gap).

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

    Tries ``GET /workspaces/{id}`` first (cheap in the common case of a
    UUID); on 404 falls back to listing workspaces and matching by
    ``key``. Raises :class:`McpApiRequestError` with ``code="not_found"``
    if neither lookup succeeds.
    """
    try:
        response = client.get(f"/workspaces/{key_or_id}")
    except McpApiRequestError as exc:
        if exc.code != "not_found":
            raise
    else:
        body: dict[str, Any] = response.json()
        return body

    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 200}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get("/workspaces", params=params)
        page = response.json()
        for item in page["items"]:
            if item["key"] == key_or_id:
                hit: dict[str, Any] = item
                return hit
        cursor = page.get("next_cursor")
        if cursor is None:
            break
    raise McpApiRequestError(
        status_code=404,
        code="not_found",
        message=f"workspace {key_or_id!r} not found",
        details={"key_or_id": key_or_id},
    )


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
