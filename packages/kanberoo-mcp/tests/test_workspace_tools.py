"""
Tests for the workspace-scoped tools.
"""

from __future__ import annotations

from conftest import MockApi, ws_body

from kanberoo_mcp.client import McpApiClient
from kanberoo_mcp.tools.workspaces import build_workspace_tools


def _handler(name: str):  # type: ignore[no-untyped-def]
    """
    Look up a workspace tool handler by its MCP name.
    """
    for tool in build_workspace_tools():
        if tool.name == name:
            return tool.handler
    raise KeyError(name)


def test_list_workspaces_returns_paginated_envelope(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    The handler returns the raw paginated envelope from the server.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [ws_body("KAN")], "next_cursor": None},
    )
    result = _handler("list_workspaces")(client, {})
    assert result["items"][0]["key"] == "KAN"
    assert result["next_cursor"] is None


def test_list_workspaces_passes_limit_and_cursor(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    Optional args land on the underlying REST call as query params.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [], "next_cursor": None},
    )
    _handler("list_workspaces")(client, {"limit": 10, "cursor": "c1"})
    recorded = mock_api.requests[-1]
    assert recorded.params == {"limit": "10", "cursor": "c1"}


def test_get_workspace_resolves_by_key(mock_api: MockApi, client: McpApiClient) -> None:
    """
    Passing a workspace key hits ``GET /workspaces/{key}`` directly.
    """
    mock_api.json("GET", "/workspaces/KAN", body=ws_body("KAN"))
    result = _handler("get_workspace")(client, {"workspace": "KAN"})
    assert result["key"] == "KAN"


def test_get_workspace_falls_back_to_list_scan(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    When ``GET /workspaces/{key}`` returns 404 the resolver scans the
    list and matches on ``key``. This is the gap where the REST API
    has no /workspaces/by-key endpoint yet.
    """
    mock_api.error(
        "GET",
        "/workspaces/KAN",
        status_code=404,
        code="not_found",
        message="not found",
    )
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [ws_body("KAN")], "next_cursor": None},
    )
    result = _handler("get_workspace")(client, {"workspace": "KAN"})
    assert result["id"] == "ws-kan"
