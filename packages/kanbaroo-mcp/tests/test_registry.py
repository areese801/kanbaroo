"""
Registry-level tests: every expected tool is present with the correct
name and shape, and the list-tools handler on the MCP server produces
the same set.
"""

from __future__ import annotations

import anyio
import mcp.types as mcp_types

from kanbaroo_mcp.client import McpApiClient
from kanbaroo_mcp.server import build_server
from kanbaroo_mcp.tools import build_registry

_EXPECTED_TOOL_NAMES = {
    "list_workspaces",
    "get_workspace",
    "list_epics",
    "create_epic",
    "update_epic",
    "list_stories",
    "get_story",
    "create_story",
    "update_story",
    "transition_story_state",
    "comment_on_story",
    "link_stories",
    "unlink_stories",
    "list_tags",
    "add_tag_to_story",
    "remove_tag_from_story",
    "get_audit_trail",
}


def test_registry_exposes_every_spec_tool() -> None:
    """
    Every tool listed in spec §6.2 is registered with the right name.
    """
    registry = build_registry()
    assert set(registry.names()) == _EXPECTED_TOOL_NAMES


def test_registry_entries_have_valid_json_schemas() -> None:
    """
    Each tool definition carries a JSON Schema object with a 'type'
    key and at least a description - the two minimums the MCP SDK
    validates against.
    """
    registry = build_registry()
    for tool in registry.tools:
        assert tool.description
        assert isinstance(tool.input_schema, dict)
        assert tool.input_schema.get("type") == "object"


def test_registry_rejects_duplicate_names() -> None:
    """
    The registry is a simple append-only list; attempting to register
    the same name twice is a programmer error.
    """
    from kanbaroo_mcp.tools.base import ToolDef, ToolRegistry

    registry = ToolRegistry()
    tool = ToolDef(
        name="dup",
        description="",
        input_schema={"type": "object"},
        handler=lambda client, args: {},
    )
    registry.register(tool)
    try:
        registry.register(tool)
    except ValueError:
        return
    raise AssertionError("duplicate registration should have raised")


def test_server_list_tools_matches_registry() -> None:
    """
    The MCP server's ``list_tools`` handler returns the same set of
    tool names the registry does, with matching descriptions.
    """
    registry = build_registry()

    def _factory() -> McpApiClient:
        raise AssertionError("list_tools must not build a client")

    server = build_server(registry, _factory)
    list_handler = server.request_handlers[mcp_types.ListToolsRequest]

    request = mcp_types.ListToolsRequest(
        method="tools/list",
        params=None,
    )
    result = anyio.run(list_handler, request)
    tools_result = result.root
    assert isinstance(tools_result, mcp_types.ListToolsResult)
    got_names = {tool.name for tool in tools_result.tools}
    assert got_names == _EXPECTED_TOOL_NAMES
    for tool in tools_result.tools:
        assert tool.description == registry.get(tool.name).description
