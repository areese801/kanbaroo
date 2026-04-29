"""
Tests for the kanban board screen.

Covers:

* Columns render in the right order and each card lands in the
  column that matches its state.
* Move mode (``m`` then ``t``) issues a
  ``POST /stories/{id}/transition`` with ``If-Match`` taken from a
  prior GET and, on success, the card appears in the target column
  after the refresh.
* A simulated ``story.created`` WebSocket event triggers a refetch
  and the new card shows up in the Backlog column.
"""

from __future__ import annotations

from kanbaroo_tui.app import KanbarooTuiApp
from kanbaroo_tui.screens.board import COLUMN_STATES, BoardScreen
from kanbaroo_tui.screens.workspace_list import WorkspaceListScreen
from kanbaroo_tui.widgets.board_column import BoardColumn
from kanbaroo_tui.widgets.story_card import StoryCard


def _workspace_list_body(items):
    return {"items": items, "next_cursor": None}


def _empty_list():
    return {"items": [], "next_cursor": None}


def _workspace(id_="ws-1", key="KAN", name="Kanbaroo"):
    return {
        "id": id_,
        "key": key,
        "name": name,
        "description": None,
        "next_issue_num": 1,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": "2026-04-17T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def _story(
    id_,
    human_id,
    *,
    state="backlog",
    priority="none",
    title="A story",
    version=1,
    workspace_id="ws-1",
):
    return {
        "id": id_,
        "workspace_id": workspace_id,
        "epic_id": None,
        "human_id": human_id,
        "title": title,
        "description": None,
        "priority": priority,
        "state": state,
        "state_actor_type": None,
        "state_actor_id": None,
        "branch_name": None,
        "commit_sha": None,
        "pr_url": None,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": "2026-04-17T00:00:00Z",
        "deleted_at": None,
        "version": version,
    }


async def _open_board(mock_api, fake_ws, tui_config, client_factory, ws_factory):
    """
    Seed the REST fake, start the app, and press enter to open the
    board for a single workspace.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    app = KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    return app


async def test_board_places_cards_in_columns(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    stories = [
        _story("story-1", "KAN-1", state="backlog"),
        _story("story-2", "KAN-2", state="todo"),
        _story("story-3", "KAN-3", state="in_progress"),
        _story("story-4", "KAN-4", state="done"),
    ]
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": stories, "next_cursor": None},
    )
    app = await _open_board(mock_api, fake_ws, tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, WorkspaceListScreen)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        board = app.screen
        assert isinstance(board, BoardScreen)
        for state_key, _ in COLUMN_STATES:
            column = board.query_one(f"#col-{state_key}", BoardColumn)
            cards = column.cards
            human_ids = {card.story["human_id"] for card in cards}
            expected = {s["human_id"] for s in stories if s["state"] == state_key}
            assert human_ids == expected, (
                f"column {state_key}: {human_ids} != {expected}"
            )
        await fake_ws.close()


async def test_move_mode_transitions_story(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    initial = [_story("story-1", "KAN-1", state="backlog", version=1)]
    moved = [_story("story-1", "KAN-1", state="todo", version=2)]
    # Three list responses: workspace-list count, board initial, then
    # the post-transition refetch. FIFO handlers are consumed in order.
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": initial, "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": initial, "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": moved, "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/stories/story-1",
        body=initial[0],
        headers={"ETag": "1"},
    )
    mock_api.json(
        "POST",
        "/stories/story-1/transition",
        body=moved[0],
        status_code=200,
    )

    app = await _open_board(mock_api, fake_ws, tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        board = app.screen
        assert isinstance(board, BoardScreen)
        # Move mode: m then t -> move first card from backlog to todo.
        await pilot.press("m")
        await pilot.pause()
        assert board.move_mode is True
        await pilot.press("t")
        await pilot.pause()
        await pilot.pause()
        assert board.move_mode is False

        backlog = board.query_one("#col-backlog", BoardColumn)
        todo = board.query_one("#col-todo", BoardColumn)
        assert [c.story["human_id"] for c in backlog.cards] == []
        assert [c.story["human_id"] for c in todo.cards] == ["KAN-1"]

        transition_requests = [
            r for r in mock_api.requests if r.path == "/stories/story-1/transition"
        ]
        assert len(transition_requests) == 1
        transition = transition_requests[0]
        assert transition.method == "POST"
        assert transition.body == {"to_state": "todo"}
        assert transition.headers.get("if-match") == "1"
        await fake_ws.close()


async def test_ws_story_created_triggers_refetch(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    initial = [_story("story-1", "KAN-1", state="backlog")]
    after = [
        _story("story-1", "KAN-1", state="backlog"),
        _story("story-2", "KAN-2", state="backlog"),
    ]
    # Three list responses for: workspace-list count, board initial,
    # board refetch triggered by the WS story.created event.
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": initial, "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": initial, "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": after, "next_cursor": None},
    )
    app = await _open_board(mock_api, fake_ws, tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        board = app.screen
        assert isinstance(board, BoardScreen)
        backlog = board.query_one("#col-backlog", BoardColumn)
        assert [c.story["human_id"] for c in backlog.cards] == ["KAN-1"]

        await fake_ws.push(
            {
                "event_id": "evt-1",
                "event_type": "story.created",
                "occurred_at": "2026-04-18T02:00:00Z",
                "actor_type": "claude",
                "actor_id": "outer-claude",
                "entity_type": "story",
                "entity_id": "story-2",
                "entity_version": 1,
                "payload": {},
            }
        )
        await pilot.pause()
        await pilot.pause()
        backlog = board.query_one("#col-backlog", BoardColumn)
        human_ids = [c.story["human_id"] for c in backlog.cards]
        assert human_ids == ["KAN-1", "KAN-2"]
        await fake_ws.close()


async def test_board_nav_bindings_priority_over_focused_card(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    With a descendant story card focused, pressing h/l/j/k still
    advances the board's cursor. Regression guard for the missing
    ``priority=True`` flag on the navigation bindings.
    """
    stories = [
        _story("story-1", "KAN-1", state="backlog"),
        _story("story-2", "KAN-2", state="backlog"),
        _story("story-3", "KAN-3", state="todo"),
    ]
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": stories, "next_cursor": None},
    )
    app = await _open_board(mock_api, fake_ws, tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        board = app.screen
        assert isinstance(board, BoardScreen)

        # A card is the focused widget after the initial load.
        assert isinstance(app.focused, StoryCard)
        assert board._active_col == 0
        assert board._active_row == 0

        # `l` advances column even with the story card holding focus.
        await pilot.press("l")
        await pilot.pause()
        assert board._active_col == 1

        # `h` moves back.
        await pilot.press("h")
        await pilot.pause()
        assert board._active_col == 0

        # `j` / `k` advance / retreat within a column.
        await pilot.press("j")
        await pilot.pause()
        assert board._active_row == 1
        await pilot.press("k")
        await pilot.pause()
        assert board._active_row == 0

        await fake_ws.close()


async def test_board_m_still_works_on_focused_card(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Non-priority bindings (``m`` for move mode) still fire when a card
    has focus. Sanity check that we did not blanket-prioritize
    everything.
    """
    stories = [_story("story-1", "KAN-1", state="backlog")]
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": stories, "next_cursor": None},
    )
    app = await _open_board(mock_api, fake_ws, tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        board = app.screen
        assert isinstance(board, BoardScreen)
        assert isinstance(app.focused, StoryCard)
        assert board.move_mode is False
        await pilot.press("m")
        await pilot.pause()
        assert board.move_mode is True
        await fake_ws.close()


async def test_board_quick_advance_moves_card_one_step(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Pressing ``>`` on a focused card transitions it to the next state
    without an intermediate move-mode keystroke.
    """
    initial = [_story("story-1", "KAN-1", state="backlog", version=1)]
    moved = [_story("story-1", "KAN-1", state="todo", version=2)]
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": initial, "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": initial, "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": moved, "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/stories/story-1",
        body=initial[0],
        headers={"ETag": "1"},
    )
    mock_api.json(
        "POST",
        "/stories/story-1/transition",
        body=moved[0],
        status_code=200,
    )

    app = await _open_board(mock_api, fake_ws, tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        board = app.screen
        assert isinstance(board, BoardScreen)
        await pilot.press("greater_than_sign")
        await pilot.pause()
        await pilot.pause()

        backlog = board.query_one("#col-backlog", BoardColumn)
        todo = board.query_one("#col-todo", BoardColumn)
        assert [c.story["human_id"] for c in backlog.cards] == []
        assert [c.story["human_id"] for c in todo.cards] == ["KAN-1"]

        transitions = [
            r for r in mock_api.requests if r.path == "/stories/story-1/transition"
        ]
        assert len(transitions) == 1
        assert transitions[0].body == {"to_state": "todo"}
        await fake_ws.close()


async def test_board_quick_advance_on_done_is_noop(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Pressing ``>`` on a card already in ``done`` flashes a no-op message
    and does not issue a transition.
    """
    stories = [_story("story-1", "KAN-1", state="done", version=1)]
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": stories, "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": stories, "next_cursor": None},
    )

    app = await _open_board(mock_api, fake_ws, tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        board = app.screen
        assert isinstance(board, BoardScreen)
        await pilot.press("greater_than_sign")
        await pilot.pause()

        transitions = [
            r for r in mock_api.requests if r.path == "/stories/story-1/transition"
        ]
        assert transitions == []
        done = board.query_one("#col-done", BoardColumn)
        assert [c.story["human_id"] for c in done.cards] == ["KAN-1"]
        await fake_ws.close()


async def test_board_quick_advance_uses_focused_card_not_indexed(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    When the focused card differs from the one tracked by the
    keyboard cursor (mouse click path), ``>`` transitions the focused
    card instead of the indexed one.
    """
    initial = [
        _story("story-1", "KAN-1", state="backlog", version=1),
        _story("story-2", "KAN-2", state="backlog", version=1),
    ]
    after = [
        _story("story-1", "KAN-1", state="backlog", version=1),
        _story("story-2", "KAN-2", state="todo", version=2),
    ]
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": initial, "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": initial, "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": after, "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/stories/story-2",
        body=initial[1],
        headers={"ETag": "1"},
    )
    mock_api.json(
        "POST",
        "/stories/story-2/transition",
        body=after[1],
        status_code=200,
    )

    app = await _open_board(mock_api, fake_ws, tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        board = app.screen
        assert isinstance(board, BoardScreen)
        # Default focus lands on KAN-1 (the screen's indexed tracker).
        focused = app.focused
        assert isinstance(focused, StoryCard)
        assert focused.story["human_id"] == "KAN-1"
        assert board._active_row == 0

        # Simulate a mouse click focusing KAN-2 directly (without going
        # through keyboard navigation).
        kan_2_card = next(
            c for c in board.query(StoryCard) if c.story["human_id"] == "KAN-2"
        )
        kan_2_card.focus()
        await pilot.pause()

        # Press `>` and assert the transition POST targets story-2.
        await pilot.press("greater_than_sign")
        await pilot.pause()
        await pilot.pause()
        transitions = [
            r
            for r in mock_api.requests
            if r.path.startswith("/stories/")
            and r.path.endswith("/transition")
            and r.method == "POST"
        ]
        assert len(transitions) == 1
        assert transitions[0].path == "/stories/story-2/transition"
        await fake_ws.close()


async def test_board_q_pops_with_focused_card(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Pressing ``q`` while a story card has focus pops back to the
    workspace list. Regression guard for ``q`` being swallowed by the
    focused descendant.
    """
    stories = [_story("story-1", "KAN-1", state="backlog")]
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": stories, "next_cursor": None},
    )
    app = await _open_board(mock_api, fake_ws, tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, BoardScreen)
        assert isinstance(app.focused, StoryCard)
        await pilot.press("q")
        await pilot.pause()
        assert isinstance(app.screen, WorkspaceListScreen)
        await fake_ws.close()
