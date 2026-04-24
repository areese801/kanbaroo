"""
Tests for the workspace-scoped tools.
"""

from __future__ import annotations

from conftest import MockApi, ws_body

from kanbaroo_mcp.client import McpApiClient
from kanbaroo_mcp.tools.workspaces import build_workspace_tools


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
    A key-shaped reference goes straight to ``/workspaces/by-key/{key}``.
    """
    mock_api.json("GET", "/workspaces/by-key/KAN", body=ws_body("KAN"))
    result = _handler("get_workspace")(client, {"workspace": "KAN"})
    assert result["key"] == "KAN"
    assert mock_api.requests[-1].path == "/workspaces/by-key/KAN"


def test_get_workspace_resolves_uuid_via_direct_endpoint(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    A UUID-shaped reference tries ``GET /workspaces/{id}`` first.
    """
    uuid = "0191a3c0-1111-7000-8000-000000000001"
    mock_api.json("GET", f"/workspaces/{uuid}", body=ws_body("KAN"))
    result = _handler("get_workspace")(client, {"workspace": uuid})
    assert result["key"] == "KAN"
    assert mock_api.requests[-1].path == f"/workspaces/{uuid}"


def test_get_workspace_uuid_falls_back_to_by_key(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    A reference that looks UUID-shaped but 404s on the direct endpoint
    retries via the by-key endpoint. Covers the edge case of a key
    that happens to contain a dash.
    """
    mock_api.error(
        "GET",
        "/workspaces/KAN-ALT",
        status_code=404,
        code="not_found",
        message="not found",
    )
    mock_api.json("GET", "/workspaces/by-key/KAN-ALT", body=ws_body("KAN-ALT"))
    result = _handler("get_workspace")(client, {"workspace": "KAN-ALT"})
    assert result["key"] == "KAN-ALT"
    assert mock_api.requests[-1].path == "/workspaces/by-key/KAN-ALT"
