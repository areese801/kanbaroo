"""
Base types for MCP tool definitions.

Every resource module (``workspaces``, ``stories``, ...) emits a list
of :class:`ToolDef` records. A :class:`ToolDef` pairs a name, a
description, a JSON Schema for the tool's inputs, and a synchronous
handler callable. The server wraps the handler in an async shim before
registering it with the MCP SDK.

Handlers take a fully-constructed :class:`McpApiClient` and the
validated input dict, and return either a Python dict (structured
content) or a list of :class:`mcp.types.ContentBlock` (for custom
text). Returning a dict is the common case.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from kanberoo_mcp.client import McpApiClient

ToolHandler = Callable[[McpApiClient, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolDef:
    """
    One tool exposed to the outer Claude.

    ``name`` is the MCP tool name (snake_case, agent-friendly).
    ``description`` is the text the outer Claude sees; it must tell
    the model when to pick this tool and what inputs it expects.
    ``input_schema`` is a JSON Schema dict that the MCP SDK validates
    arguments against before our handler runs.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


@dataclass
class ToolRegistry:
    """
    Ordered collection of :class:`ToolDef` records.

    Order matters because the MCP ``tools/list`` response preserves
    insertion order and the outer Claude's tool picker is biased by
    it. We list reads before writes within each resource.
    """

    tools: list[ToolDef] = field(default_factory=list)
    _by_name: dict[str, ToolDef] = field(default_factory=dict)

    def register(self, tool: ToolDef) -> None:
        """
        Add ``tool`` to the registry. Duplicate names are a bug and
        raise :class:`ValueError`.
        """
        if tool.name in self._by_name:
            raise ValueError(f"duplicate MCP tool name: {tool.name}")
        self.tools.append(tool)
        self._by_name[tool.name] = tool

    def get(self, name: str) -> ToolDef:
        """
        Return the tool with ``name``; raises :class:`KeyError` if
        absent.
        """
        return self._by_name[name]

    def names(self) -> list[str]:
        """
        Return every registered tool name in insertion order.
        """
        return [tool.name for tool in self.tools]
