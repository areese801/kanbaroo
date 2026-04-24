"""
Aggregate every MCP tool definition into a single registry.

Each sub-module builds a list of :class:`ToolDef` records. The server
pulls :func:`build_registry` to get the full catalogue and register it
with the MCP SDK. Splitting tools by resource keeps each file short and
makes the mental map from spec §6.2 to code straightforward.
"""

from __future__ import annotations

from kanbaroo_mcp.tools.audit import build_audit_tools
from kanbaroo_mcp.tools.base import ToolDef, ToolHandler, ToolRegistry
from kanbaroo_mcp.tools.comments import build_comment_tools
from kanbaroo_mcp.tools.epics import build_epic_tools
from kanbaroo_mcp.tools.linkages import build_linkage_tools
from kanbaroo_mcp.tools.stories import build_story_tools
from kanbaroo_mcp.tools.tags import build_tag_tools
from kanbaroo_mcp.tools.workspaces import build_workspace_tools


def build_registry() -> ToolRegistry:
    """
    Return the full :class:`ToolRegistry` for the MCP server.

    The order of insertion determines the order in which tools are
    listed to the client; we group reads before writes within each
    resource to mirror spec §6.2.
    """
    registry = ToolRegistry()
    for builder in (
        build_workspace_tools,
        build_epic_tools,
        build_story_tools,
        build_comment_tools,
        build_linkage_tools,
        build_tag_tools,
        build_audit_tools,
    ):
        for tool in builder():
            registry.register(tool)
    return registry


__all__ = [
    "ToolDef",
    "ToolHandler",
    "ToolRegistry",
    "build_registry",
]
