"""
Async WebSocket subscriber for the Kanbaroo TUI.

Connects to ``/api/v1/events?token=...`` and yields parsed event
dicts. The server interleaves two kinds of frames on that socket:

* Event envelopes shaped as ``docs/spec.md`` section 5.3 describes
  (``event_id``, ``event_type``, ...).
* Keepalive pings shaped as ``{"type": "ping", "ts": ...}`` (see
  ``kanbaroo_api.routers.events_ws``).

This module filters pings out and yields only real events so screens
can treat the stream as "things I might want to react to."

Auto-reconnect
--------------

Network hiccups or a server restart close the socket. The subscriber
reconnects with exponential backoff up to :data:`MAX_BACKOFF_SECONDS`
so the TUI recovers automatically; the REST surface is always the
source of truth, so a missed window of events costs at worst a manual
refresh.

Dependency injection
--------------------

:class:`EventSubscriber` accepts a ``connector`` callable that returns
an async iterator of parsed JSON frames. Production code uses
:func:`websockets_connector` which wraps the ``websockets`` library;
tests pass a fake connector that yields from an in-memory queue so
they can script events deterministically without a running server.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import websockets

logger = logging.getLogger(__name__)

EVENT_PING_TYPE = "ping"
DEFAULT_INITIAL_BACKOFF_SECONDS = 0.5
MAX_BACKOFF_SECONDS = 10.0

WsConnector = Callable[[str], AsyncIterator[dict[str, Any]]]


def _http_to_ws_url(api_url: str) -> str:
    """
    Rewrite an ``http[s]://host[:port]`` URL to its ``ws[s]://`` form.

    Strips any path and query so callers can compose the events-path
    and token params themselves.
    """
    parts = urlsplit(api_url.rstrip("/"))
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, "", "", ""))


def build_events_url(api_url: str, token: str) -> str:
    """
    Build the full ``ws://host/api/v1/events?token=...`` URL.

    The token goes into the query string because browsers and many
    WebSocket clients cannot set custom headers on the upgrade
    handshake; this matches ``docs/spec.md`` section 5.1.
    """
    base = _http_to_ws_url(api_url)
    return f"{base}/api/v1/events?token={token}"


async def websockets_connector(url: str) -> AsyncIterator[dict[str, Any]]:
    """
    Default connector: open a WebSocket to ``url`` and yield parsed
    JSON frames.

    Non-dict or non-JSON frames are skipped rather than raising; the
    reconnect loop in :class:`EventSubscriber` is reserved for genuine
    connection-level failures.
    """
    async with websockets.connect(url) as ws:
        async for raw in ws:
            try:
                parsed = json.loads(raw)
            except ValueError:
                logger.warning("ws: dropping non-JSON frame")
                continue
            if not isinstance(parsed, dict):
                continue
            yield parsed


class EventSubscriber:
    """
    Re-connecting subscriber around a :data:`WsConnector`.

    Yields real events only (keepalive pings are filtered out), calls
    the connector in a loop, and applies exponential backoff between
    attempts when the connector raises or the stream ends.
    """

    def __init__(
        self,
        *,
        url: str,
        connector: WsConnector | None = None,
        initial_backoff: float = DEFAULT_INITIAL_BACKOFF_SECONDS,
        max_backoff: float = MAX_BACKOFF_SECONDS,
    ) -> None:
        """
        Build a subscriber bound to ``url``.

        ``connector`` defaults to :func:`websockets_connector`;
        supplying a custom callable is how tests inject a scripted
        event stream without a network.
        """
        self._url = url
        self._connector: WsConnector = connector or websockets_connector
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff
        self._stopped = asyncio.Event()

    def stop(self) -> None:
        """
        Signal the :meth:`stream` loop to exit at its next checkpoint.
        """
        self._stopped.set()

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        """
        Yield real events forever, reconnecting on disconnect.

        Keepalive pings (``{"type": "ping", ...}``) are filtered out so
        callers can treat every yielded dict as a real event envelope.
        The backoff resets to the initial value after any successful
        frame to avoid starvation when the server flaps briefly.
        """
        backoff = self._initial_backoff
        while not self._stopped.is_set():
            try:
                async for frame in self._connector(self._url):
                    if self._stopped.is_set():
                        return
                    if frame.get("type") == EVENT_PING_TYPE:
                        continue
                    yield frame
                    backoff = self._initial_backoff
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("ws: connection error, retrying: %s", exc)
            if self._stopped.is_set():
                return
            try:
                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=backoff,
                )
                return
            except TimeoutError:
                pass
            backoff = min(backoff * 2, self._max_backoff)
