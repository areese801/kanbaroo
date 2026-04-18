"""
Tests for the global audit feed screen.

Two scenarios:

* The feed renders mock audit events when ``/audit`` returns 200 and
  appends a WebSocket-delivered event to the top.
* A 404 from ``/audit`` (cage K is still pending) falls back cleanly
  to the "endpoint not yet available" placeholder and a subsequent
  WS event still populates the table.
"""

from __future__ import annotations

import httpx
from textual.widgets import DataTable

from kanberoo_tui.app import KanberooTuiApp
from kanberoo_tui.screens.audit_feed import AuditFeedScreen


def _empty_list():
    return {"items": [], "next_cursor": None}


def _workspace():
    return {
        "id": "ws-1",
        "key": "KAN",
        "name": "Kanberoo",
        "description": None,
        "next_issue_num": 1,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": "2026-04-17T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def _audit(id_: str, action: str = "created"):
    return {
        "id": id_,
        "occurred_at": f"2026-04-18T00:00:0{id_[-1]}Z",
        "actor_type": "human",
        "actor_id": "adam",
        "entity_type": "story",
        "entity_id": f"story-{id_}",
        "action": action,
        "diff": "{}",
    }


async def test_audit_feed_renders_mock_events_and_live_ws_append(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    audit_rows = [_audit("001"), _audit("002")]
    mock_api.json(
        "GET",
        "/audit",
        body={"items": audit_rows, "next_cursor": None},
    )

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()
        feed = app.screen
        assert isinstance(feed, AuditFeedScreen)
        table = feed.query_one("#audit-table", DataTable)
        assert table.row_count == 2

        # Live WS event lands at the top.
        await fake_ws.push(
            {
                "event_id": "evt-new",
                "event_type": "story.created",
                "occurred_at": "2026-04-18T02:00:00Z",
                "actor_type": "claude",
                "actor_id": "outer-claude",
                "entity_type": "story",
                "entity_id": "story-new",
                "entity_version": 1,
                "payload": {},
            }
        )
        await pilot.pause()
        await pilot.pause()
        assert feed.events[0]["event_id"] == "evt-new"
        table = feed.query_one("#audit-table", DataTable)
        assert table.row_count == 3
        await fake_ws.close()


async def test_audit_feed_tolerates_404_and_still_shows_live_events(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.add(
        "GET",
        "/audit",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "cage K"}},
        ),
    )

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        await pilot.pause()
        feed = app.screen
        assert isinstance(feed, AuditFeedScreen)
        # Placeholder should be present; the table is empty.
        placeholders = feed.query(".audit-empty")
        assert len(placeholders) == 1

        await fake_ws.push(
            {
                "event_id": "evt-live",
                "event_type": "story.created",
                "occurred_at": "2026-04-18T02:00:00Z",
                "actor_type": "claude",
                "actor_id": "outer-claude",
                "entity_type": "story",
                "entity_id": "story-new",
                "entity_version": 1,
                "payload": {},
            }
        )
        await pilot.pause()
        await pilot.pause()
        table = feed.query_one("#audit-table", DataTable)
        assert table.row_count == 1
        assert feed.events[0]["event_id"] == "evt-live"
        await fake_ws.close()
