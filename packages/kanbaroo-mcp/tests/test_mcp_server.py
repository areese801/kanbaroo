"""
Tests for the MCP server's dispatch layer.

These drive the server's ``call_tool`` handler directly (no stdio
transport) to verify error translation, tool not-found, and that a
happy-path tool call returns structured content the MCP SDK then
serializes into a CallToolResult.
"""

from __future__ import annotations

from typing import Any

import anyio
import mcp.types as mcp_types
from conftest import MockApi, ws_body

from kanbaroo_mcp.client import McpApiClient
from kanbaroo_mcp.server import build_server
from kanbaroo_mcp.tools import build_registry


def _call(
    server: Any,
    name: str,
    args: dict[str, Any],
) -> mcp_types.CallToolResult:
    """
    Invoke the registered call-tool handler for ``name`` with ``args``.

    Returns the raw :class:`CallToolResult` so tests can assert on
    isError, structuredContent, or content blocks.
    """
    handler = server.request_handlers[mcp_types.CallToolRequest]
    request = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(name=name, arguments=args),
    )
    result = anyio.run(handler, request)
    payload = result.root
    assert isinstance(payload, mcp_types.CallToolResult)
    return payload


def test_call_tool_unknown_name_returns_error(mock_api: MockApi) -> None:
    """
    Calling an unregistered tool name returns an error result, not a
    server-level exception.
    """
    del mock_api

    def _factory() -> McpApiClient:
        raise AssertionError("client must not be built for unknown tools")

    server = build_server(build_registry(), _factory)
    result = _call(server, "no_such_tool", {})
    assert result.isError is True


def test_call_tool_happy_path_returns_structured_content(
    mock_api: MockApi,
) -> None:
    """
    A successful tool call produces structured content and non-error.
    """
    mock_api.json("GET", "/workspaces/by-key/KAN", body=ws_body("KAN"))
    transport = mock_api.transport()

    def _factory() -> McpApiClient:
        return McpApiClient(
            base_url="http://test.invalid",
            token="t",
            transport=transport,
        )

    server = build_server(build_registry(), _factory)
    result = _call(server, "get_workspace", {"workspace": "KAN"})
    assert result.isError in (False, None)
    assert result.structuredContent is not None
    assert result.structuredContent["key"] == "KAN"


def test_call_tool_api_error_translated_to_error_result(
    mock_api: MockApi,
) -> None:
    """
    An :class:`McpApiRequestError` from a handler is converted into an
    error content block rather than crashing the server.
    """
    mock_api.error(
        "GET",
        "/workspaces/by-key/MISSING",
        status_code=404,
        code="not_found",
        message="workspace missing",
    )
    transport = mock_api.transport()

    def _factory() -> McpApiClient:
        return McpApiClient(
            base_url="http://test.invalid",
            token="t",
            transport=transport,
        )

    server = build_server(build_registry(), _factory)
    result = _call(server, "get_workspace", {"workspace": "MISSING"})
    assert result.isError is True
    assert any(
        isinstance(block, mcp_types.TextContent) and "not_found" in block.text
        for block in result.content
    )
