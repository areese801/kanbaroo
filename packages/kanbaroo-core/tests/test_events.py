"""
Unit tests for :mod:`kanbaroo_core.events`.

The event bus is a simple in-process fan-out broker: these tests
exercise its fan-out behaviour, subscriber lifecycle, and backpressure
policy (drop, do not block) without touching the database.
"""

import asyncio
import contextlib

import pytest

from kanbaroo_core.events import DEFAULT_SUBSCRIBER_QUEUE_CAPACITY, Event, EventBus


def _make_event(event_id: str, event_type: str = "test.event") -> Event:
    """
    Build a minimal :class:`Event` for bus tests.

    Field content is irrelevant beyond ``event_id`` (which identifies
    events in assertions); tests only care that the whole envelope is
    delivered unchanged.
    """
    return Event(
        event_id=event_id,
        event_type=event_type,
        occurred_at="2026-04-18T00:00:00Z",
        actor_type="human",
        actor_id="adam",
        entity_type="workspace",
        entity_id="ws-1",
        entity_version=1,
        payload={"marker": event_id},
    )


async def _wait_subscribers(bus: EventBus, expected: int) -> None:
    """
    Spin until the bus reports ``expected`` subscribers.

    Subscription registration happens on the first ``await`` inside
    :meth:`EventBus.subscribe`, so tests that publish immediately after
    creating a consumer task need to yield until the queue is in the
    bus's subscriber set.
    """
    while bus.subscriber_count < expected:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_two_subscribers_receive_the_same_event() -> None:
    """
    Fan-out invariant: every subscriber registered at publish time
    sees the event.
    """
    bus = EventBus()
    received_a: list[Event] = []
    received_b: list[Event] = []

    async def consume(target: list[Event], count: int) -> None:
        async for event in bus.subscribe():
            target.append(event)
            if len(target) >= count:
                return

    task_a = asyncio.create_task(consume(received_a, 1))
    task_b = asyncio.create_task(consume(received_b, 1))
    await _wait_subscribers(bus, 2)

    event = _make_event("evt-1")
    bus.publish(event)

    await asyncio.wait_for(task_a, timeout=1)
    await asyncio.wait_for(task_b, timeout=1)

    assert received_a == [event]
    assert received_b == [event]


@pytest.mark.asyncio
async def test_unsubscribe_cleans_up_registrations() -> None:
    """
    Cancelling a subscribing task tears down the subscription.

    Cancellation raises :class:`asyncio.CancelledError` inside the
    ``await queue.get()`` in :meth:`EventBus.subscribe`, which fires
    the generator's ``finally`` clause synchronously before the task
    completes, so the assertion that follows ``await task`` sees a
    bus with zero subscribers.
    """
    bus = EventBus()

    async def consume_forever() -> None:
        async for _event in bus.subscribe():
            pass

    task = asyncio.create_task(consume_forever())
    await _wait_subscribers(bus, 1)
    assert bus.subscriber_count == 1

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert bus.subscriber_count == 0


@pytest.mark.asyncio
async def test_full_queue_drops_only_for_that_subscriber() -> None:
    """
    A saturated subscriber queue must not affect other subscribers:
    events delivered to the saturated queue are dropped, events
    delivered to healthy queues arrive intact.
    """
    bus = EventBus()  # default (large) capacity for the healthy sub.
    slow_capacity = 2
    healthy_events: list[Event] = []
    stuck_entered = asyncio.Event()

    async def stuck_subscriber() -> None:
        subscription = bus.subscribe(capacity=slow_capacity)
        try:
            await subscription.__anext__()  # receive the first event
            stuck_entered.set()
            await asyncio.Event().wait()  # block forever
        finally:
            await subscription.aclose()

    async def healthy_subscriber(target: list[Event], count: int) -> None:
        async for event in bus.subscribe():
            target.append(event)
            if len(target) >= count:
                return

    stuck_task = asyncio.create_task(stuck_subscriber())
    await _wait_subscribers(bus, 1)

    total_events = slow_capacity + 3  # 5 events overflow a 2-slot queue
    healthy_task = asyncio.create_task(healthy_subscriber(healthy_events, total_events))
    await _wait_subscribers(bus, 2)

    events = [_make_event(f"evt-{i}") for i in range(total_events)]
    for event in events:
        bus.publish(event)

    await asyncio.wait_for(stuck_entered.wait(), timeout=1)
    await asyncio.wait_for(healthy_task, timeout=1)

    # The healthy subscriber receives every published event.
    assert healthy_events == events

    # Stuck subscriber's queue overflowed silently; the publisher never
    # raised and the healthy task completed despite the saturation.
    stuck_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await stuck_task
    assert bus.subscriber_count == 0


def test_event_to_dict_round_trip() -> None:
    """
    ``Event.to_dict`` returns the wire envelope shape from spec §5.3
    with every field present.
    """
    event = _make_event("evt-dict")
    envelope = event.to_dict()
    assert set(envelope.keys()) == {
        "event_id",
        "event_type",
        "occurred_at",
        "actor_type",
        "actor_id",
        "entity_type",
        "entity_id",
        "entity_version",
        "payload",
    }
    assert envelope["event_id"] == "evt-dict"
    assert envelope["payload"] == {"marker": "evt-dict"}


def test_default_queue_capacity_matches_module_constant() -> None:
    """
    ``EventBus`` without an explicit capacity uses the module default.
    """
    bus = EventBus()
    assert bus._queue_capacity == DEFAULT_SUBSCRIBER_QUEUE_CAPACITY
