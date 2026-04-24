"""
Shared fixtures for the Kanbaroo MCP server test suite.

Every test that exercises a tool handler drives the handler through
a :class:`MockApi` - the same pattern the CLI tests use. Tool
handlers never spin up a real stdio transport in tests; they run as
plain sync callables, which is the whole reason the registry stores
them that way.
"""

from __future__ import annotations

import json as _json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from kanbaroo_mcp.client import API_PREFIX, McpApiClient

RouteHandler = Callable[[httpx.Request], httpx.Response]


@dataclass
class RecordedRequest:
    """
    A single HTTP call captured by :class:`MockApi`.
    """

    method: str
    path: str
    params: dict[str, str]
    headers: dict[str, str]
    body: Any


@dataclass
class MockApi:
    """
    Programmable in-memory HTTP fake for the MCP server.

    Routes are matched on ``(method, path)`` where ``path`` is the
    portion after ``/api/v1``. Registrations for the same route are
    returned in order when multiple are queued (so a test can script a
    412-then-200 sequence against a single PATCH endpoint).
    """

    routes: dict[tuple[str, str], list[RouteHandler]] = field(default_factory=dict)
    requests: list[RecordedRequest] = field(default_factory=list)

    def add(
        self,
        method: str,
        path: str,
        handler: RouteHandler,
    ) -> None:
        """
        Register ``handler`` as the next response for ``(method, path)``.
        """
        key = (method.upper(), path)
        self.routes.setdefault(key, []).append(handler)

    def json(
        self,
        method: str,
        path: str,
        *,
        status_code: int = 200,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """
        Convenience helper that registers a JSON response directly.
        """

        def _respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code,
                json=body,
                headers=headers or {},
            )

        self.add(method, path, _respond)

    def error(
        self,
        method: str,
        path: str,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """
        Register an error response using the canonical envelope shape.
        """
        envelope: dict[str, Any] = {"error": {"code": code, "message": message}}
        if details is not None:
            envelope["error"]["details"] = details
        self.json(method, path, status_code=status_code, body=envelope)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        """
        Route dispatch. Records the request then looks up a handler.
        """
        path = request.url.path
        if path.startswith(API_PREFIX):
            path = path[len(API_PREFIX) :]
        body: Any = None
        if request.content:
            try:
                body = _json.loads(request.content)
            except ValueError:
                body = request.content
        params = {k: v for k, v in request.url.params.multi_items()}
        self.requests.append(
            RecordedRequest(
                method=request.method,
                path=path,
                params=params,
                headers=dict(request.headers),
                body=body,
            )
        )
        key = (request.method, path)
        handlers = self.routes.get(key)
        if not handlers:
            raise AssertionError(
                f"MockApi received unregistered request: {request.method} {path}"
            )
        if len(handlers) == 1:
            return handlers[0](request)
        handler = handlers.pop(0)
        return handler(request)

    def transport(self) -> httpx.MockTransport:
        """
        Return the :class:`httpx.MockTransport` bound to this fake.
        """
        return httpx.MockTransport(self._handle)


@pytest.fixture
def mock_api() -> Iterator[MockApi]:
    """
    Fresh :class:`MockApi` per test.
    """
    yield MockApi()


@pytest.fixture
def client(mock_api: MockApi) -> Iterator[McpApiClient]:
    """
    A :class:`McpApiClient` pointed at the mock transport.
    """
    with McpApiClient(
        base_url="http://test.invalid",
        token="kbr_mcp_test",
        transport=mock_api.transport(),
    ) as c:
        yield c


def ws_body(key: str = "KAN") -> dict[str, Any]:
    """
    Canned workspace body matching :class:`WorkspaceRead`.
    """
    return {
        "id": f"ws-{key.lower()}",
        "key": key,
        "name": f"{key} workspace",
        "description": None,
        "next_issue_num": 1,
        "created_at": "2026-04-18T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def story_body(
    *,
    human_id: str = "KAN-1",
    story_id: str = "story-1",
    state: str = "backlog",
    version: int = 1,
    description: str | None = None,
    workspace_id: str = "ws-kan",
) -> dict[str, Any]:
    """
    Canned story body matching :class:`StoryRead`.
    """
    return {
        "id": story_id,
        "workspace_id": workspace_id,
        "epic_id": None,
        "human_id": human_id,
        "title": f"story {human_id}",
        "description": description,
        "priority": "none",
        "state": state,
        "state_actor_type": None,
        "state_actor_id": None,
        "branch_name": None,
        "commit_sha": None,
        "pr_url": None,
        "created_at": "2026-04-18T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
        "deleted_at": None,
        "version": version,
    }


def epic_body(
    *,
    human_id: str = "KAN-4",
    epic_id: str = "epic-1",
    state: str = "open",
    version: int = 1,
) -> dict[str, Any]:
    """
    Canned epic body matching :class:`EpicRead`.
    """
    return {
        "id": epic_id,
        "workspace_id": "ws-kan",
        "human_id": human_id,
        "title": f"epic {human_id}",
        "description": None,
        "state": state,
        "created_at": "2026-04-18T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
        "deleted_at": None,
        "version": version,
    }


def tag_body(*, tag_id: str = "tag-1", name: str = "bug") -> dict[str, Any]:
    """
    Canned tag body matching :class:`TagRead`.
    """
    return {
        "id": tag_id,
        "workspace_id": "ws-kan",
        "name": name,
        "color": None,
        "created_at": "2026-04-18T00:00:00Z",
        "deleted_at": None,
    }
