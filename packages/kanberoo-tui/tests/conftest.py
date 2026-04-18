"""
Shared fixtures for the Kanberoo TUI test suite.

Two pieces of infrastructure live here:

* :class:`MockApi` is an :class:`httpx.MockTransport`-backed fake so
  screens can fetch from the REST surface without a running server.
  Routes are registered ``(method, path)`` and the same fake records
  every request it receives for assertions.
* :class:`FakeWsStream` and its factory helper let tests script a
  WebSocket event timeline. Every ``push`` delivers one real event
  (pings are tested separately in the subscriber tests); the app's
  ws task pulls from the stream exactly the same way it pulls from
  the real :class:`~kanberoo_tui.ws.EventSubscriber`.

Together they let every UI test drive a fully configured app through
``run_test`` without the network, without a server, and without
monkey-patching module-level state.
"""

from __future__ import annotations

import asyncio
import json as _json
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from kanberoo_tui.client import API_PREFIX, AsyncApiClient
from kanberoo_tui.config import TuiConfig

RouteHandler = Callable[[httpx.Request], httpx.Response]


@dataclass
class RecordedRequest:
    """
    A single HTTP call captured by :class:`MockApi`.
    """

    method: str
    path: str
    headers: dict[str, str]
    body: Any


@dataclass
class MockApi:
    """
    Programmable in-memory HTTP fake for the TUI.

    Matches the shape used by the CLI tests so porting route setup
    between suites is mechanical. Routes are matched on
    ``(method, path)`` where ``path`` is the part after ``/api/v1``.
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
        Convenience helper that registers a JSON response.

        When called once for a ``(method, path)`` the handler answers
        every matching request. When called twice or more for the
        same pair, handlers are consumed FIFO so tests can script a
        series of distinct responses against the same URL.
        """

        def _respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code,
                json=body,
                headers=headers or {},
            )

        self.add(method, path, _respond)

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
        self.requests.append(
            RecordedRequest(
                method=request.method,
                path=path,
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
        Return an async :class:`httpx.MockTransport` bound to this fake.
        """
        return httpx.MockTransport(self._handle)


class FakeWsStream:
    """
    Test-double for the WebSocket event stream.

    Tests call :meth:`push` to deliver one event at a time; the app's
    ws task consumes them via the async iterator returned from
    :meth:`iterator`. Calling :meth:`close` ends the stream so the ws
    task exits cleanly and ``run_test`` can tear down.
    """

    def __init__(self) -> None:
        """
        Build an empty, open stream.
        """
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def push(self, event: dict[str, Any]) -> None:
        """
        Deliver ``event`` to the consumer on the next ``next()``.
        """
        await self._queue.put(event)

    async def close(self) -> None:
        """
        Signal end-of-stream.
        """
        await self._queue.put(None)

    async def iterator(self) -> AsyncIterator[dict[str, Any]]:
        """
        Async-iterate events until :meth:`close` is called.
        """
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event


@pytest.fixture
def mock_api() -> Iterator[MockApi]:
    """
    Fresh :class:`MockApi` per test.
    """
    yield MockApi()


@pytest.fixture
def fake_ws() -> FakeWsStream:
    """
    Fresh :class:`FakeWsStream` per test.
    """
    return FakeWsStream()


@pytest.fixture
def tui_config(tmp_path):
    """
    Minimal :class:`TuiConfig` pointing at a fake host.
    """
    return TuiConfig(
        api_url="http://test.invalid",
        token="kbr_test",
        config_path=tmp_path / "config.toml",
    )


@pytest.fixture
def client_factory(mock_api):
    """
    Returns a client factory that builds an
    :class:`AsyncApiClient` bound to the :class:`MockApi`.
    """

    def _factory(config):
        return AsyncApiClient(
            base_url=config.api_url,
            token=config.token,
            transport=mock_api.transport(),
        )

    return _factory


@pytest.fixture
def ws_factory(fake_ws):
    """
    Returns a ws factory that hands out the fixture-scoped
    :class:`FakeWsStream` iterator.
    """

    def _factory(config):
        return fake_ws.iterator()

    return _factory
