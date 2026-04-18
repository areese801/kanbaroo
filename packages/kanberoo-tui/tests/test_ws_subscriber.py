"""
Unit tests for the WebSocket subscriber.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from kanberoo_tui.ws import EventSubscriber, build_events_url


def test_build_events_url_ws():
    assert (
        build_events_url("http://localhost:8080", "kbr_x")
        == "ws://localhost:8080/api/v1/events?token=kbr_x"
    )


def test_build_events_url_wss():
    assert (
        build_events_url("https://host", "tok") == "wss://host/api/v1/events?token=tok"
    )


@pytest.mark.asyncio
async def test_subscriber_filters_ping_frames():
    frames: list[dict[str, Any]] = [
        {"type": "ping", "ts": "2026-04-18T00:00:00Z"},
        {"event_id": "a", "event_type": "story.created"},
        {"type": "ping", "ts": "2026-04-18T00:00:01Z"},
        {"event_id": "b", "event_type": "story.updated"},
    ]

    async def fake_connector(_url: str) -> AsyncIterator[dict[str, Any]]:
        for frame in frames:
            yield frame

    subscriber = EventSubscriber(
        url="ws://ignored",
        connector=fake_connector,
        initial_backoff=0,
        max_backoff=0,
    )
    received: list[dict[str, Any]] = []

    async def consume() -> None:
        async for event in subscriber.stream():
            received.append(event)
            if len(received) == 2:
                subscriber.stop()
                return

    await consume()
    assert [e["event_id"] for e in received] == ["a", "b"]
