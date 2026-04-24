"""
Kanbaroo MCP server entry point.

The server is a thin translator between the MCP tool protocol and the
Kanbaroo REST API. It runs as a subprocess of the outer client
(Claude Desktop or equivalent), speaks JSON-RPC over stdio, and
routes each tool call to the corresponding resource handler in
``kanbaroo_mcp.tools.*``.

Responsibilities:

* Parse command-line flags (``--api-url``, ``--token-env``, ``--token``).
* Resolve configuration via :func:`kanbaroo_mcp.config.resolve_config`.
* Detect whether the resolved token is actor_type=claude; log a
  warning if not, but never gate startup on it.
* Register every tool defined in :func:`kanbaroo_mcp.tools.build_registry`
  with the official MCP SDK's :class:`Server`.
* Run the stdio transport loop.

Test hooks: :func:`build_server` returns a configured :class:`Server`
plus the :class:`ToolRegistry`. Handlers are exposed as plain sync
callables on the registry so tests can drive them without spinning up
the stdio transport.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from collections.abc import Sequence
from typing import Any

import anyio
import mcp.types as mcp_types
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server

from kanbaroo_mcp import __version__
from kanbaroo_mcp.client import (
    McpApiClient,
    McpApiError,
    McpApiRequestError,
)
from kanbaroo_mcp.config import ConfigError, McpConfig, resolve_config
from kanbaroo_mcp.tools import ToolRegistry, build_registry

_LOG = logging.getLogger("kanbaroo_mcp")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """
    Parse the command-line flags documented in spec §6.3.
    """
    parser = argparse.ArgumentParser(
        prog="kanbaroo-mcp",
        description=(
            "Kanbaroo MCP server: serves the Kanbaroo REST API as MCP tools over stdio."
        ),
    )
    parser.add_argument(
        "--api-url",
        dest="api_url",
        default=None,
        help=(
            "Base URL of the Kanbaroo API (e.g. http://localhost:8080). "
            "Falls back to $KANBAROO_API_URL then to config.toml."
        ),
    )
    parser.add_argument(
        "--token-env",
        dest="token_env",
        default=None,
        help=(
            "Name of an environment variable whose value is the API "
            "token. Preferred over --token because the plaintext does "
            "not appear on the command line."
        ),
    )
    parser.add_argument(
        "--token",
        dest="token",
        default=None,
        help=(
            "API token plaintext. Handy for local testing; prefer "
            "--token-env for real deployments."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"kanbaroo-mcp {__version__}",
    )
    return parser.parse_args(list(argv))


def _check_actor_type(client: McpApiClient, token: str) -> str | None:
    """
    Best-effort detection of the resolved token's ``actor_type``.

    Returns ``"claude"`` when we can confirm the token is claude-typed,
    some other actor type string when we can confirm it is not, or
    ``None`` when the server did not give us enough information to
    decide (for example if ``/tokens`` is not listable with this
    token's permissions). We deliberately do not gate startup on this
    call: a failure here is a warning, not a fatal error.
    """
    try:
        response = client.get("/tokens")
    except McpApiError:
        return None
    try:
        tokens = response.json()
    except ValueError:
        return None
    if not isinstance(tokens, list):
        return None
    expected_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    for row in tokens:
        if not isinstance(row, dict):
            continue
        if row.get("token_hash") == expected_hash:
            actor_type = row.get("actor_type")
            if isinstance(actor_type, str):
                return actor_type
    return None


def _warn_if_non_claude_token(client: McpApiClient, config: McpConfig) -> None:
    """
    Log a stderr warning if the resolved token is not actor_type=claude.

    The warning is informational; the server continues either way. An
    MCP deployment that uses a human-typed token still works, it just
    means mutations will be attributed to the human in the audit log.
    """
    actor_type = _check_actor_type(client, config.token)
    if actor_type is None:
        _LOG.info(
            "could not determine actor_type for token (source=%s); "
            "proceeding without the startup warning check",
            config.token_source,
        )
        return
    if actor_type == "claude":
        _LOG.info(
            "kanbaroo-mcp ready: api_url=%s token_source=%s actor_type=claude",
            config.api_url,
            config.token_source,
        )
        return
    _LOG.warning(
        "kanbaroo-mcp token has actor_type=%s (source=%s). Mutations "
        "made through this MCP server will be attributed as %s, not "
        "claude. For AI-agent workflows create a dedicated token with "
        "actor_type=claude via 'kb token create --actor-type claude'.",
        actor_type,
        config.token_source,
        actor_type,
    )


def _format_tool_error(exc: Exception) -> list[mcp_types.ContentBlock]:
    """
    Translate an exception from a tool handler into an MCP text
    content block.
    """
    if isinstance(exc, McpApiRequestError):
        text = f"[{exc.code}] {exc.message}"
        if exc.details:
            text = f"{text} ({exc.details})"
    elif isinstance(exc, McpApiError):
        text = str(exc)
    else:
        text = f"{type(exc).__name__}: {exc}"
    return [mcp_types.TextContent(type="text", text=text)]


def build_server(
    registry: ToolRegistry,
    client_factory: Any,
) -> Server[object, object]:
    """
    Wire a :class:`Server` with list-tools and call-tool handlers that
    delegate to ``registry``.

    ``client_factory`` is a zero-argument callable returning an
    :class:`McpApiClient`. Tests pass a factory that produces
    :class:`httpx.MockTransport` backed clients; production passes a
    factory that builds against the real API.
    """
    server: Server[object, object] = Server(
        "kanbaroo-mcp",
        version=__version__,
        instructions=(
            "Kanbaroo issue tracker. Use list_workspaces and "
            "list_stories to discover work; create_story, update_story, "
            "and transition_story_state to drive it."
        ),
    )

    @server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _list_tools() -> list[mcp_types.Tool]:
        """
        Return every registered tool as an MCP ``Tool``.
        """
        return [
            mcp_types.Tool(
                name=tool.name,
                description=tool.description,
                inputSchema=tool.input_schema,
            )
            for tool in registry.tools
        ]

    @server.call_tool()  # type: ignore[untyped-decorator]
    async def _call_tool(
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | mcp_types.CallToolResult:
        """
        Dispatch the tool call to the matching handler. A dict result
        is forwarded as ``structuredContent``; a :class:`CallToolResult`
        is forwarded verbatim (used for error shapes).
        """
        try:
            tool = registry.get(name)
        except KeyError:
            return mcp_types.CallToolResult(
                content=[
                    mcp_types.TextContent(
                        type="text",
                        text=f"unknown tool: {name}",
                    )
                ],
                isError=True,
            )

        client = client_factory()
        try:
            result = await anyio.to_thread.run_sync(tool.handler, client, arguments)
        except Exception as exc:
            return mcp_types.CallToolResult(
                content=_format_tool_error(exc),
                isError=True,
            )
        finally:
            client.close()
        return result

    return server


def _build_client_factory(config: McpConfig) -> Any:
    """
    Return a zero-arg callable that produces a fresh
    :class:`McpApiClient` per tool call.

    A fresh client per call keeps connection pooling simple and avoids
    sharing state across concurrent MCP requests.
    """

    def _factory() -> McpApiClient:
        return McpApiClient(base_url=config.api_url, token=config.token)

    return _factory


def _configure_logging() -> None:
    """
    Log to stderr so the client's stdin/stdout protocol stream is
    untouched. Keep the default level at INFO; operators can raise to
    DEBUG via $KANBAROO_MCP_LOG_LEVEL.
    """
    import os

    level_name = os.environ.get("KANBAROO_MCP_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        stream=sys.stderr,
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _serve(server: Server[object, object]) -> None:
    """
    Run the MCP server over the stdio transport until the client
    disconnects.
    """
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(
                notification_options=NotificationOptions(),
            ),
        )


def main(argv: Sequence[str] | None = None) -> int:
    """
    Console script entry point.

    Returns the process exit code; the ``kanbaroo-mcp`` wrapper in
    ``pyproject.toml`` uses :func:`sys.exit` to bubble it up.
    """
    _configure_logging()
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        config = resolve_config(
            cli_api_url=args.api_url,
            cli_token=args.token,
            cli_token_env=args.token_env,
        )
    except ConfigError as exc:
        print(f"kanbaroo-mcp: {exc}", file=sys.stderr)
        return 1

    factory = _build_client_factory(config)
    with factory() as probe_client:
        _warn_if_non_claude_token(probe_client, config)

    registry = build_registry()
    server = build_server(registry, factory)
    try:
        anyio.run(_serve, server)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
