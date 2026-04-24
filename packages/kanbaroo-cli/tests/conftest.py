"""
Shared fixtures for the Kanbaroo CLI test suite.

Every CLI test that exercises an HTTP surface uses ``MockApi`` to
script the responses the fake server returns and asserts on the
captured request trace. Wiring the fake through
:func:`kanbaroo_cli.context.set_client_factory` keeps command handlers
identical between production and tests: we never monkey-patch the
handlers themselves.
"""

from __future__ import annotations

import json as _json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from kanbaroo_cli.client import API_PREFIX, ApiClient
from kanbaroo_cli.context import set_client_factory

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
    Programmable in-memory HTTP fake for the CLI.

    Routes are matched on ``(method, path)`` where ``path`` is the
    portion after ``/api/v1``. Callers register expected routes via
    :meth:`add` and any request that hits an unknown route raises an
    assertion inside the transport, surfacing as a clean test failure.
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
        Multiple registrations for the same route are returned in order.
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

    def bytes(
        self,
        method: str,
        path: str,
        *,
        content: bytes,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        """
        Register a binary response (used by ``kb export``).
        """

        def _respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code,
                content=content,
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
        # Single-handler routes repeat; multi-handler routes are consumed
        # FIFO so tests can script a series of distinct responses against
        # the same URL.
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
    Fresh :class:`MockApi` per test with the client factory swapped
    to return clients that use its transport.
    """
    fake = MockApi()

    def _factory(config: Any) -> ApiClient:
        return ApiClient(
            base_url=config.api_url,
            token=config.token,
            transport=fake.transport(),
        )

    set_client_factory(_factory)
    try:
        yield fake
    finally:
        set_client_factory(None)


@pytest.fixture
def config_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """
    Create a temporary Kanbaroo config directory with a minimal
    ``config.toml`` pointing at a fake server, and redirect
    ``$KANBAROO_CONFIG_DIR`` there.
    """
    monkeypatch.setenv("KANBAROO_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("KANBAROO_API_URL", raising=False)
    monkeypatch.delenv("KANBAROO_TOKEN", raising=False)
    monkeypatch.delenv("KANBAROO_DATABASE_URL", raising=False)
    (tmp_path / "config.toml").write_text(
        'api_url = "http://test.invalid"\n'
        'token = "kbr_test"\n'
        f'database_url = "sqlite:///{tmp_path / "kanbaroo.db"}"\n',
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def runner() -> CliRunner:
    """
    Typer ``CliRunner``. The underlying ``click.testing.Result`` already
    exposes stdout and stderr separately on modern Click, so no
    ``mix_stderr`` arg is required.
    """
    return CliRunner()
