"""
WebSocket notification endpoint.

Clients connect to ``/api/v1/events?token=<plaintext>`` to subscribe to
every event published on :data:`kanberoo_core.events.default_bus`.

Authentication
--------------

The token is supplied as a query parameter rather than an
``Authorization`` header because browsers cannot set custom headers on
a WebSocket upgrade. This matches ``docs/spec.md`` section 5.1. Any of
(missing token, empty token, unknown/revoked token) closes the
connection with close code ``1008`` (policy violation) before ``accept``
is called, so the handshake itself signals rejection.

Subscription protocol
---------------------

On connect the client is automatically subscribed to every event; the
spec defers scoped subscriptions to a future multi-user phase.
Incoming messages from the client are read and discarded: the
subscription is fire-and-forget, so we only read to detect
disconnection promptly.

Keepalive ping
--------------

Every :data:`EVENT_WS_PING_INTERVAL` seconds the server sends a
:data:`PING_MESSAGE_TYPE`-typed message to keep NAT / proxy timeouts
at bay. The ping is deliberately NOT shaped like an
:class:`~kanberoo_core.events.Event` envelope: it carries
``{"type": "ping", "ts": ...}`` with no ``event_id`` or
``event_type``, so naive clients that filter on ``event_type`` never
mistake it for a real event. Tests patch the interval down via the
``EVENT_WS_PING_INTERVAL`` environment variable so keepalive
assertions complete in seconds rather than half a minute.
"""

import asyncio
import contextlib
import logging
import os

from fastapi import APIRouter, Query, WebSocket, status
from starlette.websockets import WebSocketDisconnect, WebSocketState

from kanberoo_core.actor import Actor
from kanberoo_core.auth import validate_token
from kanberoo_core.events import default_bus
from kanberoo_core.time import utc_now_iso

logger = logging.getLogger(__name__)

DEFAULT_PING_INTERVAL_SECONDS = 30.0
PING_MESSAGE_TYPE = "ping"


def _resolve_ping_interval() -> float:
    """
    Read ``EVENT_WS_PING_INTERVAL`` (seconds) with a safe default.

    Tests override this to ~1 second so keepalive assertions do not
    need a 30-second wait. Invalid values fall back to the default
    rather than crashing the server at connect time.
    """
    raw = os.environ.get("EVENT_WS_PING_INTERVAL")
    if not raw:
        return DEFAULT_PING_INTERVAL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "ignoring invalid EVENT_WS_PING_INTERVAL=%r; using default %ss",
            raw,
            DEFAULT_PING_INTERVAL_SECONDS,
        )
        return DEFAULT_PING_INTERVAL_SECONDS
    if value <= 0:
        return DEFAULT_PING_INTERVAL_SECONDS
    return value


router = APIRouter(tags=["events"])


@router.websocket("/events")
async def events_ws(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    """
    Serve the live event stream for one WebSocket client.

    The handler validates the token synchronously against a
    short-lived session, accepts the upgrade, then fans out three
    cooperating tasks: one forwards bus events, one sends periodic
    pings, one drains inbound frames so a client disconnect is noticed
    promptly. When any of them finishes (for any reason) the others
    are cancelled and the socket is closed.
    """
    if not token:
        # close() before accept() causes Starlette to respond to the
        # handshake with HTTP 403; that is acceptable (and more visible
        # to curl-style debugging than a post-accept 1008), but for
        # WebSocket-aware clients we follow up with an explicit 1008
        # close after accept to match the spec's rejection code.
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    actor = _validate_query_token(websocket, token)
    if actor is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    logger.info(
        "events_ws: connected actor_type=%s actor_id=%s",
        actor.type,
        actor.id,
    )

    ping_interval = _resolve_ping_interval()
    forward_task = asyncio.create_task(_forward_events(websocket))
    ping_task = asyncio.create_task(_keepalive(websocket, ping_interval))
    recv_task = asyncio.create_task(_drain_incoming(websocket))
    tasks = {forward_task, ping_task, recv_task}
    try:
        _done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(
                asyncio.CancelledError,
                WebSocketDisconnect,
                Exception,
            ):
                await task
        if websocket.application_state != WebSocketState.DISCONNECTED:
            with contextlib.suppress(Exception):
                await websocket.close()


def _validate_query_token(websocket: WebSocket, token: str) -> Actor | None:
    """
    Validate ``token`` against ``api_tokens`` and return the attributed
    actor, or ``None`` if the token is unknown or revoked.

    Uses a freshly-opened session against the app's session factory
    so ``last_used_at`` is stamped and persisted even though the
    surrounding WebSocket flow owns no transaction.
    """
    factory = websocket.app.state.session_factory
    session = factory()
    try:
        actor = validate_token(session, token)
        if actor is None:
            session.rollback()
            return None
        session.commit()
        return actor
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def _forward_events(websocket: WebSocket) -> None:
    """
    Pump events from the bus into the websocket until the client
    disconnects.

    Each :class:`~kanberoo_core.events.Event` is dumped to its dict
    form and sent as JSON. The subscription is torn down automatically
    when this coroutine is cancelled or returns.
    """
    async for event in default_bus.subscribe():
        await websocket.send_json(event.to_dict())


async def _keepalive(websocket: WebSocket, interval: float) -> None:
    """
    Send a keepalive ping every ``interval`` seconds until cancelled.

    The ping payload is documented in the module docstring; it does
    NOT share a shape with :class:`~kanberoo_core.events.Event` so
    clients can dispatch on ``type == "ping"`` without confusing it
    for an event missing ``event_type``.
    """
    while True:
        await asyncio.sleep(interval)
        await websocket.send_json({"type": PING_MESSAGE_TYPE, "ts": utc_now_iso()})


async def _drain_incoming(websocket: WebSocket) -> None:
    """
    Consume and discard inbound frames so disconnects are noticed.

    We do not define an inbound message protocol in v1; anything a
    client sends is ignored. The only reason to read is that
    Starlette only surfaces disconnection through ``receive_*`` calls.
    """
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        return
