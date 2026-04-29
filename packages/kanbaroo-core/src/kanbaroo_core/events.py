"""
In-process pub/sub bus for Kanbaroo WebSocket events.

Every service mutation that writes an ``audit_events`` row also publishes
a notification event onto the bus defined here. Subscribers (the
WebSocket ``/api/v1/events`` handler, tests) consume events as an
asyncio stream.

Transaction ordering
--------------------

The load-bearing invariant: **no event is visible to a subscriber until
the SQLAlchemy transaction that produced it has committed**. If the
transaction rolls back, the subscriber sees nothing. Leaking events for
rolled-back work would let clients observe phantom mutations.

We implement this by buffering events on ``Session.info`` and flushing
them to the bus from a session-level ``after_commit`` listener (and
clearing them from an ``after_rollback`` listener). The buffering
helper lives in :mod:`kanbaroo_core.services.events`, which also
registers the listeners as a side effect of import. See that module's
docstring for the exact plumbing.

Thread safety
-------------

The API runs sync FastAPI endpoints in Starlette's threadpool, so
:func:`EventBus.publish` is typically called from a worker thread while
subscribers' ``asyncio.Queue`` objects belong to the uvicorn event
loop. ``publish`` therefore schedules each ``put_nowait`` via
:meth:`asyncio.AbstractEventLoop.call_soon_threadsafe`, which is the
only thread-safe way to feed an ``asyncio.Queue``. Tests running in a
single event loop pay one extra scheduler tick per publish.

Backpressure policy
-------------------

Subscribers get bounded queues (capacity 256). If a subscriber falls
behind and its queue fills up we **drop** the event for that subscriber
and log a warning. A dropped notification is not a correctness problem:
clients refetch from REST on reconnect, and the authoritative state
lives in the database, not the event stream. The alternative, blocking
the publisher until a slow subscriber catches up, would stall other
subscribers and (worse) the request that triggered the mutation.

Single-process scope
--------------------

The default bus is a process-local singleton. Multi-process fan-out
(e.g. across uvicorn workers behind a load balancer) is out of scope
for v1; that would require a proper message broker. The single-process
assumption matches the single-binary deployment target in
``docs/spec.md`` section 2.
"""

import asyncio
import logging
import threading
from collections.abc import AsyncGenerator
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_SUBSCRIBER_QUEUE_CAPACITY = 256


@dataclass(frozen=True, slots=True)
class Event:
    """
    One notification event, as defined by ``docs/spec.md`` section 5.3.

    The envelope fields match the spec exactly so the dict returned by
    :meth:`to_dict` is the wire shape clients see on the WebSocket.

    ``entity_version`` is ``None`` for entities that have no ``version``
    column (linkages, tags, tag associations) and for events where the
    entity itself was not modified (for example ``story.commented`` is
    a child event of the story but does not bump the story's version).
    """

    event_id: str
    event_type: str
    occurred_at: str
    actor_type: str
    actor_id: str
    entity_type: str
    entity_id: str
    entity_version: int | None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        Return the event as a plain dict suitable for JSON encoding.

        ``asdict`` deep-copies the payload so downstream consumers
        cannot mutate the stored event by mutating what they receive.
        """
        return asdict(self)


class EventBus:
    """
    Process-local fan-out bus for :class:`Event` values.

    Subscribers are asyncio queues. Publishers are synchronous. Every
    publish attempts to deliver to every current subscriber; a full
    queue drops the event for that subscriber only and does not affect
    other subscribers or the publisher.
    """

    def __init__(
        self,
        *,
        queue_capacity: int = DEFAULT_SUBSCRIBER_QUEUE_CAPACITY,
    ) -> None:
        """
        Build a fresh bus with an empty subscriber set.
        """
        self._queue_capacity = queue_capacity
        self._subscribers: dict[asyncio.Queue[Event], asyncio.AbstractEventLoop] = {}
        self._lock = threading.Lock()

    @property
    def subscriber_count(self) -> int:
        """
        Current number of registered subscribers.

        Exposed for tests and observability; not part of the public
        contract.
        """
        with self._lock:
            return len(self._subscribers)

    def publish(self, event: Event) -> None:
        """
        Hand ``event`` to every current subscriber without blocking.

        If a subscriber's queue is full the event is dropped for that
        subscriber and a warning is logged. The publisher is never
        blocked by a slow subscriber.
        """
        with self._lock:
            targets = list(self._subscribers.items())
        for queue, loop in targets:
            try:
                loop.call_soon_threadsafe(self._deliver, queue, event)
            except RuntimeError:
                # The subscriber's loop has been closed between our
                # snapshot and now. The subscribe() ``finally`` clause
                # will clean up on the next call; just skip delivery.
                logger.debug(
                    "event bus: subscriber loop closed, dropping event %s",
                    event.event_id,
                )

    @staticmethod
    def _deliver(queue: "asyncio.Queue[Event]", event: Event) -> None:
        """
        Queue-side put that tolerates a full queue.

        Scheduled via ``call_soon_threadsafe`` so it always runs on the
        subscriber's event loop; ``put_nowait`` is therefore safe.
        """
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "event bus: dropping event %s for a slow subscriber",
                event.event_id,
            )

    async def subscribe(
        self, *, capacity: int | None = None
    ) -> AsyncGenerator[Event, None]:
        """
        Async-iterate over events delivered after subscription.

        The subscription is registered on entry and torn down when the
        async generator is closed (through ``aclose()``, cancellation
        of the consuming task, or garbage collection). The cleanest
        way to unsubscribe is to cancel the task running the
        ``async for`` loop; Python's generator finalization then runs
        the teardown code synchronously.

        ``capacity`` overrides the bus-level queue capacity for a
        single subscriber. The override exists primarily so tests can
        exercise the drop-on-full policy without having to saturate a
        256-slot queue.

        Events published before :meth:`subscribe` is called are never
        replayed; this is a notification channel, not a durable log.
        """
        loop = asyncio.get_running_loop()
        queue_capacity = capacity if capacity is not None else self._queue_capacity
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=queue_capacity)
        with self._lock:
            self._subscribers[queue] = loop
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            with self._lock:
                self._subscribers.pop(queue, None)


default_bus = EventBus()
"""
The module-level bus every service publishes to and every subscriber
reads from. Single-process fan-out is sufficient for v1; replacing it
with a cross-process broker would mean swapping this singleton for a
remote client.
"""
