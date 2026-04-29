"""
Optimistic-concurrency helpers for MCP tool handlers.

The REST API rejects mutations whose ``If-Match`` version does not
match the current row with a ``412 Precondition Failed``. When an
outer agent is driving the board there is a real chance that the
entity it read a moment ago was just touched by a human in the TUI;
in that case the right behavior is to refetch, re-apply the patch,
and try once more.

:func:`with_retry_on_412` wraps a mutation callable in exactly that
retry: on a first 412 the callable is invoked a second time with the
freshly-fetched ETag. On a second 412 we surface a clean
"try again, the entity changed underneath us" error rather than
looping forever.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import httpx

from kanbaroo_mcp.client import McpApiClient, McpApiRequestError

T = TypeVar("T")


def with_retry_on_412(
    client: McpApiClient,
    entity_path: str,
    operation: Callable[[str], httpx.Response],
) -> httpx.Response:
    """
    Invoke ``operation`` with the current ETag of ``entity_path``;
    retry once on ``412``.

    ``operation`` receives the ETag string and is expected to issue
    the mutation (PATCH, transition POST, etc.). If the first attempt
    raises :class:`McpApiRequestError` with ``status_code == 412`` we
    refetch the ETag and call ``operation`` again. A second 412 is
    translated into a :class:`McpApiRequestError` with a clearer
    message so the outer agent knows the retry itself failed.
    """
    etag = client.fetch_etag(entity_path)
    try:
        return operation(etag)
    except McpApiRequestError as exc:
        if exc.status_code != 412:
            raise
    fresh_etag = client.fetch_etag(entity_path)
    try:
        return operation(fresh_etag)
    except McpApiRequestError as exc:
        if exc.status_code == 412:
            raise McpApiRequestError(
                status_code=412,
                code=exc.code,
                message=(
                    f"{entity_path} changed twice during this MCP call. "
                    "Try again; the entity is changing faster than the "
                    "retry loop can follow."
                ),
                details=exc.details,
            ) from exc
        raise
