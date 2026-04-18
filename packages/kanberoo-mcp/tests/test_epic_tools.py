"""
Tests for the epic-scoped tools.
"""

from __future__ import annotations

from conftest import MockApi, epic_body, ws_body

from kanberoo_mcp.client import McpApiClient
from kanberoo_mcp.tools.epics import build_epic_tools


def _handler(name: str):  # type: ignore[no-untyped-def]
    for tool in build_epic_tools():
        if tool.name == name:
            return tool.handler
    raise KeyError(name)


def test_list_epics_resolves_workspace(mock_api: MockApi, client: McpApiClient) -> None:
    """
    ``list_epics`` resolves the workspace key first and returns the
    server's paginated envelope unchanged.
    """
    mock_api.json("GET", "/workspaces/KAN", body=ws_body("KAN"))
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/epics",
        body={"items": [epic_body()], "next_cursor": None},
    )
    result = _handler("list_epics")(client, {"workspace": "KAN"})
    assert result["items"][0]["human_id"] == "KAN-4"


def test_create_epic_posts_payload(mock_api: MockApi, client: McpApiClient) -> None:
    """
    ``create_epic`` resolves the workspace and POSTs title +
    description.
    """
    mock_api.json("GET", "/workspaces/KAN", body=ws_body("KAN"))
    mock_api.json(
        "POST",
        "/workspaces/ws-kan/epics",
        status_code=201,
        body=epic_body(),
    )
    result = _handler("create_epic")(
        client,
        {"workspace": "KAN", "title": "v2 redesign", "description": "md"},
    )
    assert result["epic"]["human_id"] == "KAN-4"
    post = [r for r in mock_api.requests if r.method == "POST"][0]
    assert post.body == {"title": "v2 redesign", "description": "md"}


def test_update_epic_patches_state(mock_api: MockApi, client: McpApiClient) -> None:
    """
    Setting ``state='closed'`` translates into a PATCH with
    If-Match, not a ``/close`` action.
    """
    mock_api.json("GET", "/epics/by-key/KAN-4", body=epic_body(version=2))
    mock_api.json(
        "GET",
        "/epics/epic-1",
        body=epic_body(version=2),
        headers={"etag": "2"},
    )
    mock_api.json(
        "PATCH",
        "/epics/epic-1",
        body=epic_body(version=3, state="closed"),
    )
    result = _handler("update_epic")(
        client,
        {"epic": "KAN-4", "state": "closed"},
    )
    assert result["epic"]["state"] == "closed"
    patch = [r for r in mock_api.requests if r.method == "PATCH"][0]
    assert patch.body == {"state": "closed"}
    assert patch.headers.get("if-match") == "2"


def test_update_epic_noop_skips_patch(mock_api: MockApi, client: McpApiClient) -> None:
    """
    With no fields the handler short-circuits; no PATCH is issued.
    """
    mock_api.json("GET", "/epics/by-key/KAN-4", body=epic_body())
    result = _handler("update_epic")(client, {"epic": "KAN-4"})
    assert result["message"] == "no fields to update"
    assert all(r.method == "GET" for r in mock_api.requests)
