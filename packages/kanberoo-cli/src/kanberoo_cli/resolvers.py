"""
ID-resolution helpers shared by commands.

Stories and epics are addressed in the CLI by their ``{KEY}-{N}`` human
identifiers (``KAN-123``); workspaces are addressed by their short key
(``KAN``) or by UUID. The REST API serves by-key lookups for stories
and epics directly; for workspaces we scan the workspace list because
no by-key endpoint exists.
"""

from __future__ import annotations

from typing import Any

from kanberoo_cli.client import ApiClient, ApiRequestError


def _looks_like_human_id(candidate: str) -> bool:
    """
    Return True if ``candidate`` is shaped like ``{KEY}-{N}``.
    """
    if "-" not in candidate:
        return False
    head, tail = candidate.rsplit("-", 1)
    return bool(head) and tail.isdigit()


def resolve_workspace(client: ApiClient, key_or_id: str) -> dict[str, Any]:
    """
    Resolve a workspace by short key or UUID and return its full body.

    Tries ``GET /workspaces/{id}`` first (cheap on the common case of a
    UUID); on 404 falls back to listing workspaces and matching by
    ``key``. Raises :class:`ApiRequestError` with ``code="not_found"``
    if neither lookup succeeds.
    """
    try:
        response = client.get(f"/workspaces/{key_or_id}")
    except ApiRequestError as exc:
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
    raise ApiRequestError(
        status_code=404,
        code="not_found",
        message=f"workspace {key_or_id!r} not found",
        details={"key_or_id": key_or_id},
    )


def resolve_story(client: ApiClient, ref: str) -> dict[str, Any]:
    """
    Resolve a story by ``{KEY}-{N}`` human id or by UUID.

    Uses ``GET /stories/by-key/{ref}`` when ``ref`` matches the
    human-id pattern, otherwise treats ``ref`` as a UUID and calls
    ``GET /stories/{ref}``.
    """
    if _looks_like_human_id(ref):
        response = client.get(f"/stories/by-key/{ref}")
    else:
        response = client.get(f"/stories/{ref}")
    body: dict[str, Any] = response.json()
    return body


def resolve_epic(client: ApiClient, ref: str) -> dict[str, Any]:
    """
    Resolve an epic by ``{KEY}-{N}`` human id or by UUID.

    Uses ``GET /epics/by-key/{ref}`` when ``ref`` matches the human-id
    pattern, otherwise treats ``ref`` as a UUID and calls
    ``GET /epics/{ref}``.
    """
    if _looks_like_human_id(ref):
        response = client.get(f"/epics/by-key/{ref}")
    else:
        response = client.get(f"/epics/{ref}")
    body: dict[str, Any] = response.json()
    return body
