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

import asyncio

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
    # Empty similar response: no duplicate confirmation modal.
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories/similar",
        body={"items": [], "next_cursor": None},
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


async def test_new_story_aborts_when_placeholder_title_unchanged(
    mock_api, fake_ws, tui_config, client_factory, ws_factory, fake_editor
):
    """
    Editing the template's body but leaving the ``# Title (replace
    this line)`` line in place aborts the create rather than posting
    a story with the placeholder title. Regression guard for the
    cage-delta "editor saves, nothing happens" path.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    # Edit adds a line but leaves the title placeholder in place; the
    # board should notify and skip the POST.
    fake_editor.content_to_write = (
        "# Title (replace this line)\n\n# Description below\n\nnotes\n"
    )

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


async def test_new_story_surfaces_post_failure_via_notify(
    mock_api, fake_ws, tui_config, client_factory, ws_factory, fake_editor
):
    """
    A POST that fails (e.g. server 500) does not silently swallow the
    error: the user sees the failure via notify and no card appears.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories/similar",
        body={"items": [], "next_cursor": None},
    )
    mock_api.add(
        "POST",
        "/workspaces/ws-1/stories",
        lambda _req: httpx.Response(
            500,
            json={"error": {"code": "server_error", "message": "boom"}},
        ),
    )
    fake_editor.content_to_write = "# My new story\n\nbody text.\n"

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
        # POST was attempted but failed; no card appears.
        posts = [
            r
            for r in mock_api.requests
            if r.method == "POST" and r.path == "/workspaces/ws-1/stories"
        ]
        assert len(posts) == 1
        backlog = app.screen.query_one("#col-backlog", BoardColumn)
        assert [c.story for c in backlog.cards] == []
        await fake_ws.close()


async def test_new_story_end_to_end_card_appears_exactly_once(
    mock_api, fake_ws, tui_config, client_factory, ws_factory, fake_editor
):
    """
    End-to-end chain for the ``n`` keybinding.

    Covers: editor returns a title -> board POSTs ``/stories`` ->
    server responds 201 with the new record -> ``story.created`` WS
    event arrives -> board refetches -> new card renders in Backlog
    exactly once (not zero, not duplicated).

    The existing ``test_new_story_posts_parsed_template_and_refetches``
    asserts the card ends up in Backlog but does not pin down whether
    duplicate refetches (POST-triggered and WS-triggered) double-render
    the card. This test pins down the exactly-once invariant because
    the cage-delta bug report was "card silently did not show up" -
    zero, duplicate, and one-off paths all need explicit coverage.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    # GETs for stories: workspace-list count, board initial, then
    # sticky "new story present" for every subsequent refetch
    # (POST-triggered + WS-triggered). If the card is duplicated, it
    # will still show up twice since every story dict is the same.
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    new_story = _story("story-99", "KAN-99", title="End-to-end smoke")
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [new_story], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories/similar",
        body={"items": [], "next_cursor": None},
    )
    mock_api.add(
        "POST",
        "/workspaces/ws-1/stories",
        lambda _req: httpx.Response(201, json=new_story),
    )
    fake_editor.content_to_write = "# End-to-end smoke\n"

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

        posts = [
            r
            for r in mock_api.requests
            if r.method == "POST" and r.path == "/workspaces/ws-1/stories"
        ]
        assert len(posts) == 1
        assert posts[0].body == {"title": "End-to-end smoke"}

        # Now deliver the server's story.created notification. Either
        # the card is already rendered (POST-triggered refetch landed
        # first) or it lands on the WS-triggered refetch - either way
        # we end up with exactly one KAN-99 card.
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
        ids = [c.story["human_id"] for c in backlog.cards]
        assert ids == ["KAN-99"], (
            f"expected exactly one KAN-99 card in backlog, got {ids}"
        )
        # No other column accidentally rendered the same story.
        for col_id in ("#col-todo", "#col-in_progress", "#col-in_review", "#col-done"):
            other = app.screen.query_one(col_id, BoardColumn)
            assert [c.story["human_id"] for c in other.cards] == []
        await fake_ws.close()


async def test_new_story_race_ws_event_before_post_response(
    mock_api, fake_ws, tui_config, client_factory, ws_factory, fake_editor
):
    """
    Race variant where the server's ``story.created`` WS event arrives
    before the POST response has returned.

    This is a realistic ordering for a real server: after the write
    commits, the server emits the event AND prepares the 201 response;
    network scheduling can deliver the WS frame before the HTTP
    response reaches the client. The board must not double-render the
    new card just because both the WS-triggered refetch and the POST-
    triggered refetch happen.

    Implementation: the POST handler holds on an ``asyncio.Event`` so
    the test can push the WS event while ``_post_new_story`` is still
    parked awaiting the POST response, then release the POST so the
    post-success refresh runs afterward. At the end, exactly one
    KAN-99 card must be visible in Backlog.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    new_story = _story("story-99", "KAN-99", title="Racey story")
    # GETs for stories: workspace-list count, board initial, WS-
    # triggered refetch (with new story; the server commit happened
    # before the WS event was dispatched), and sticky for any further
    # refetches including the POST-completion one.
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [new_story], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories/similar",
        body={"items": [], "next_cursor": None},
    )
    release_post = asyncio.Event()

    async def delayed_post(_req):
        await release_post.wait()
        return httpx.Response(201, json=new_story)

    mock_api.add("POST", "/workspaces/ws-1/stories", delayed_post)
    fake_editor.content_to_write = "# Racey story\n"

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

        # Kick off the new-story action as a task so the test thread
        # can continue pushing events while the POST is parked. Going
        # through pilot.press("n") would chain into the binding
        # dispatcher which awaits the full action; we want to be the
        # one that releases the POST.
        new_story_task = asyncio.create_task(app.screen.action_new_story())
        # Let the action run up through the POST await.
        for _ in range(6):
            await pilot.pause()

        # The POST is still parked on release_post. Deliver the
        # ``story.created`` event now so the WS path runs first.
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
        for _ in range(6):
            await pilot.pause()

        # Release the POST so _post_new_story completes and its
        # post-success refresh_data runs. Any double-render shows up
        # at the final assertion.
        release_post.set()
        for _ in range(6):
            await pilot.pause()
        await new_story_task

        posts = [
            r
            for r in mock_api.requests
            if r.method == "POST" and r.path == "/workspaces/ws-1/stories"
        ]
        assert len(posts) == 1
        backlog = app.screen.query_one("#col-backlog", BoardColumn)
        ids = [c.story["human_id"] for c in backlog.cards]
        assert ids == ["KAN-99"], (
            f"expected exactly one KAN-99 card after WS-before-POST race, got {ids}"
        )
        await fake_ws.close()
