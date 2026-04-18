"""
Tests for the board ``n`` keybinding (new story via ``$EDITOR``).

Focuses on three things:

* The template is round-tripped through the fake editor.
* A POST to ``/workspaces/{id}/stories`` is issued with the parsed
  title and description.
* A subsequent WebSocket ``story.created`` event causes the board to
  refetch, and the new card appears in the Backlog column.
"""

from __future__ import annotations

import httpx

from kanberoo_tui.app import KanberooTuiApp
from kanberoo_tui.screens.board import BoardScreen
from kanberoo_tui.widgets.board_column import BoardColumn


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


def _story(id_, human_id, title="A story"):
    return {
        "id": id_,
        "workspace_id": "ws-1",
        "epic_id": None,
        "human_id": human_id,
        "title": title,
        "description": None,
        "priority": "none",
        "state": "backlog",
        "state_actor_type": None,
        "state_actor_id": None,
        "branch_name": None,
        "commit_sha": None,
        "pr_url": None,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": "2026-04-17T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


async def test_new_story_posts_parsed_template_and_refetches(
    mock_api, fake_ws, tui_config, client_factory, ws_factory, fake_editor
):
    # Workspace list + counts.
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    # Three list responses for board: workspace-list count, board
    # initial, and board refetch after the WS story.created event.
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={
            "items": [_story("story-99", "KAN-99", title="My new story")],
            "next_cursor": None,
        },
    )
    # POST story endpoint: the template output populates the body.
    new_story = _story("story-99", "KAN-99", title="My new story")
    mock_api.add(
        "POST",
        "/workspaces/ws-1/stories",
        lambda _req: httpx.Response(201, json=new_story),
    )
    # Fake editor fills the template with a real title and description.
    fake_editor.content_to_write = "# My new story\n\nSome description text.\n"

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
        editor_runner=fake_editor,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, BoardScreen)

        await pilot.press("n")
        await pilot.pause()
        await pilot.pause()

        create_requests = [
            r
            for r in mock_api.requests
            if r.method == "POST" and r.path == "/workspaces/ws-1/stories"
        ]
        assert len(create_requests) == 1
        payload = create_requests[0].body
        assert payload == {
            "title": "My new story",
            "description": "Some description text.",
        }

        # Simulate the server's ws.story.created event so the board
        # refetches (the third pre-registered story list response
        # contains the new card).
        await fake_ws.push(
            {
                "event_id": "evt-1",
                "event_type": "story.created",
                "occurred_at": "2026-04-18T02:00:00Z",
                "actor_type": "human",
                "actor_id": "adam",
                "entity_type": "story",
                "entity_id": "story-99",
                "entity_version": 1,
                "payload": {},
            }
        )
        await pilot.pause()
        await pilot.pause()
        backlog = app.screen.query_one("#col-backlog", BoardColumn)
        assert [c.story["human_id"] for c in backlog.cards] == ["KAN-99"]
        await fake_ws.close()


async def test_new_story_aborts_on_unchanged_template(
    mock_api, fake_ws, tui_config, client_factory, ws_factory, fake_editor
):
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    # Editor rewrites the template with no material change (same
    # placeholder title). Without an explicit POST route the test will
    # trip MockApi's assertion if the abort logic is broken.
    fake_editor.content_to_write = None

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
        editor_runner=fake_editor,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        await pilot.pause()
        creates = [
            r
            for r in mock_api.requests
            if r.method == "POST" and r.path == "/workspaces/ws-1/stories"
        ]
        assert creates == []
        await fake_ws.close()
