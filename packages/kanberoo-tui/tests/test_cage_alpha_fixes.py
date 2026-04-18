"""
Tests for the cage alpha TUI fix bundle.

Covers the nine items called out in the human validation pass:

* Keyboard tab navigation on story detail (numeric + ``]``).
* Tag picker / LinkPicker j/k keyboard nav.
* Global ``W`` / ``E`` / ``A`` bindings from a deep stack.
* Screen title banners (sub_title set on mount).
* ``q`` confirm modal and rapid double-tap fast exit.
* Skip-empty-column board navigation.
* Emoji actor badge rendering and ``TERM`` fallback.

Editor-crash fix (item 1) and priority-color tweak (item 8) are
exercised from :mod:`test_editor` and the snapshot of the card
markup respectively; no additional live-TUI pilot is required for
those.
"""

from __future__ import annotations

from typing import Any

import httpx
from textual.widgets import SelectionList, TabbedContent

from kanberoo_tui.app import KanberooTuiApp
from kanberoo_tui.screens.audit_feed import AuditFeedScreen
from kanberoo_tui.screens.board import BoardScreen
from kanberoo_tui.screens.epic_list import EpicListScreen
from kanberoo_tui.screens.story_detail import StoryDetailScreen
from kanberoo_tui.screens.workspace_list import (
    QuitConfirmModal,
    WorkspaceListScreen,
)
from kanberoo_tui.widgets.board_column import BoardColumn
from kanberoo_tui.widgets.story_card import (
    ACTOR_EMOJI,
    ACTOR_LABELS,
    _terminal_supports_emoji,
    actor_badge,
)


def _empty_list():
    return {"items": [], "next_cursor": None}


def _workspace_list_body(items):
    return {"items": items, "next_cursor": None}


def _workspace(id_="ws-1", key="KAN", name="Kanberoo"):
    return {
        "id": id_,
        "key": key,
        "name": name,
        "description": None,
        "next_issue_num": 1,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def _story(
    id_,
    human_id,
    *,
    state="backlog",
    priority="none",
    workspace_id="ws-1",
    state_actor_type=None,
):
    return {
        "id": id_,
        "workspace_id": workspace_id,
        "epic_id": None,
        "human_id": human_id,
        "title": f"Story {human_id}",
        "description": None,
        "priority": priority,
        "state": state,
        "state_actor_type": state_actor_type,
        "state_actor_id": None,
        "branch_name": None,
        "commit_sha": None,
        "pr_url": None,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": "2026-04-17T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def _seed_detail_routes(mock_api, *, story, extra_fetches: int = 1):
    """
    Register detail-screen routes for ``story``. Mirrors the helper in
    :mod:`test_story_detail` but without the cross-test coupling.
    """
    for _ in range(extra_fetches + 1):
        mock_api.add(
            "GET",
            f"/stories/{story['id']}",
            lambda _req, body=story: httpx.Response(
                200,
                json=body,
                headers={"ETag": str(body["version"])},
            ),
        )
    mock_api.json("GET", f"/stories/{story['id']}/comments", body=_empty_list())
    mock_api.json("GET", f"/stories/{story['id']}/comments", body=_empty_list())
    mock_api.json("GET", f"/stories/{story['id']}/linkages", body=_empty_list())
    mock_api.json("GET", f"/stories/{story['id']}/linkages", body=_empty_list())
    mock_api.add(
        "GET",
        f"/audit/entity/story/{story['id']}",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "cage K"}},
        ),
    )
    mock_api.add(
        "GET",
        f"/audit/entity/story/{story['id']}",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "cage K"}},
        ),
    )


async def _open_detail(app, pilot):
    """
    Navigate workspace -> board -> detail.
    """
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()
    assert isinstance(app.screen, BoardScreen)
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()
    assert isinstance(app.screen, StoryDetailScreen)


# ---------------------------------------------------------------------
# Item 2: keyboard tab navigation on story detail
# ---------------------------------------------------------------------


async def test_story_detail_numeric_tab_jump(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Pressing ``3`` on the story detail activates the linkages tab.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story("story-1", "KAN-1")], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story("story-1", "KAN-1")], "next_cursor": None},
    )
    _seed_detail_routes(mock_api, story=_story("story-1", "KAN-1"))

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await _open_detail(app, pilot)
        detail = app.screen
        assert isinstance(detail, StoryDetailScreen)
        tabs = detail.query_one("#story-tabs", TabbedContent)
        assert tabs.active == "tab-description"
        await pilot.press("3")
        await pilot.pause()
        assert tabs.active == "tab-linkages"
        await fake_ws.close()


async def test_story_detail_bracket_advances_tab(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    ``]`` walks forward through the tab list one at a time.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story("story-1", "KAN-1")], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story("story-1", "KAN-1")], "next_cursor": None},
    )
    _seed_detail_routes(mock_api, story=_story("story-1", "KAN-1"))

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await _open_detail(app, pilot)
        detail = app.screen
        assert isinstance(detail, StoryDetailScreen)
        tabs = detail.query_one("#story-tabs", TabbedContent)
        assert tabs.active == "tab-description"
        await pilot.press("]")
        await pilot.pause()
        assert tabs.active == "tab-comments"
        await pilot.press("]")
        await pilot.pause()
        assert tabs.active == "tab-linkages"
        await fake_ws.close()


# ---------------------------------------------------------------------
# Item 3: tag picker keyboard nav
# ---------------------------------------------------------------------


async def test_tag_picker_focuses_selection_list_on_open(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Opening the tag picker focuses the SelectionList so j/k and
    space/enter work immediately.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story("story-1", "KAN-1")], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story("story-1", "KAN-1")], "next_cursor": None},
    )
    _seed_detail_routes(mock_api, story=_story("story-1", "KAN-1"))
    mock_api.json(
        "GET",
        "/workspaces/ws-1/tags",
        body={
            "items": [
                {"id": "t-1", "name": "backend", "color": None},
                {"id": "t-2", "name": "frontend", "color": None},
            ],
            "next_cursor": None,
        },
    )

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await _open_detail(app, pilot)
        await pilot.press("t")
        await pilot.pause()
        await pilot.pause()
        picker = app.screen.query_one("#tag-picker-list", SelectionList)
        assert app.focused is picker
        await fake_ws.close()


async def test_tag_picker_j_moves_selection_cursor(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Pressing ``j`` on the tag picker advances the selection cursor.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story("story-1", "KAN-1")], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story("story-1", "KAN-1")], "next_cursor": None},
    )
    _seed_detail_routes(mock_api, story=_story("story-1", "KAN-1"))
    mock_api.json(
        "GET",
        "/workspaces/ws-1/tags",
        body={
            "items": [
                {"id": "t-1", "name": "backend", "color": None},
                {"id": "t-2", "name": "frontend", "color": None},
            ],
            "next_cursor": None,
        },
    )

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await _open_detail(app, pilot)
        await pilot.press("t")
        await pilot.pause()
        await pilot.pause()
        picker = app.screen.query_one("#tag-picker-list", SelectionList)
        initial = picker.highlighted
        await pilot.press("j")
        await pilot.pause()
        moved = picker.highlighted
        assert moved is not None
        assert moved != initial
        await fake_ws.close()


# ---------------------------------------------------------------------
# Item 4: global W/E/A bindings
# ---------------------------------------------------------------------


async def test_app_W_returns_to_workspace_list_from_deep_stack(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    From the board (one screen above workspace list), ``W`` pops back
    to the workspace list.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story("story-1", "KAN-1")], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story("story-1", "KAN-1")], "next_cursor": None},
    )

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, BoardScreen)
        await pilot.press("W")
        await pilot.pause()
        assert isinstance(app.screen, WorkspaceListScreen)
        await fake_ws.close()


async def test_app_E_from_board_opens_epic_list(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    ``E`` from the board opens the epic list for the current workspace.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story("story-1", "KAN-1")], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story("story-1", "KAN-1")], "next_cursor": None},
    )
    # Epic list's own fetch:
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, BoardScreen)
        await pilot.press("E")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EpicListScreen)
        # Stack was reset: workspace list sits beneath the new epic
        # list; the implicit default screen lives at index 0.
        assert len(app.screen_stack) == 3
        assert isinstance(app.screen_stack[1], WorkspaceListScreen)
        await fake_ws.close()


async def test_app_A_opens_audit_feed_from_any_screen(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    ``A`` resets the stack and pushes the global audit feed.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story("story-1", "KAN-1")], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story("story-1", "KAN-1")], "next_cursor": None},
    )
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
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, BoardScreen)
        await pilot.press("A")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, AuditFeedScreen)
        await fake_ws.close()


# ---------------------------------------------------------------------
# Item 5: screen title banners
# ---------------------------------------------------------------------


async def test_workspace_list_title_is_set(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    The workspace list sets a descriptive sub_title.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.sub_title == "Workspaces"
        await fake_ws.close()


async def test_board_title_includes_workspace_key(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    The board screen's sub_title names the workspace and the screen.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, BoardScreen)
        assert app.screen.sub_title == "KAN - Board"
        await fake_ws.close()


# ---------------------------------------------------------------------
# Item 6: q confirm + qq fast exit
# ---------------------------------------------------------------------


async def test_single_q_opens_confirm_modal(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Single ``q`` on the workspace list pushes the confirm modal; the
    app stays alive.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert isinstance(app.screen, QuitConfirmModal)
        assert app._exit is False
        await fake_ws.close()


async def test_quit_modal_escape_returns_to_list(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Escape on the confirm modal dismisses and returns to the list.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        assert isinstance(app.screen, QuitConfirmModal)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, WorkspaceListScreen)
        assert app._exit is False
        await fake_ws.close()


async def test_quit_modal_enter_quits(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Enter on the confirm modal quits the app.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app._exit is True
        await fake_ws.close()


async def test_double_q_fast_exit_gate(monkeypatch):
    """
    Two ``action_quit_with_confirm`` invocations separated by less
    than :data:`FAST_QUIT_WINDOW_SECONDS` trigger the fast-exit path.

    Unit-tests the gate without spinning up the whole TUI: the screen
    is constructed standalone, ``time.monotonic`` and the screen's
    ``app`` are stubbed, and the test asserts the first call pushes
    the modal while the second reaches ``App.exit``.
    """
    from unittest.mock import patch

    from kanberoo_tui.screens.workspace_list import (
        FAST_QUIT_WINDOW_SECONDS,
        WorkspaceListScreen,
    )

    screen = WorkspaceListScreen()
    exit_calls: list[bool] = []
    push_calls: list[Any] = []

    class _FakeApp:
        async def push_screen(self, modal, callback=None):  # type: ignore[no-untyped-def]
            push_calls.append(modal)

        def exit(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            exit_calls.append(True)

    fake_app = _FakeApp()
    ticks = iter([100.0, 100.1])

    def _fake_monotonic() -> float:
        try:
            return next(ticks)
        except StopIteration:
            return 100.1

    monkeypatch.setattr(
        "kanberoo_tui.screens.workspace_list.time.monotonic",
        _fake_monotonic,
    )
    with patch.object(WorkspaceListScreen, "app", fake_app):
        await screen.action_quit_with_confirm()
        assert len(push_calls) == 1
        assert exit_calls == []
        await screen.action_quit_with_confirm()
        assert len(push_calls) == 1
        assert exit_calls == [True]
    assert FAST_QUIT_WINDOW_SECONDS == 0.5


# ---------------------------------------------------------------------
# Item 7: skip empty columns on board navigation
# ---------------------------------------------------------------------


async def test_board_l_skips_empty_columns(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    With cards in Backlog, Todo, and Done only, a single ``l`` press
    from Todo lands on Done.
    """
    stories = [
        _story("story-1", "KAN-1", state="backlog"),
        _story("story-2", "KAN-2", state="todo"),
        _story("story-3", "KAN-3", state="done"),
    ]
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
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

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        board = app.screen
        assert isinstance(board, BoardScreen)
        # Active column starts at backlog (0).
        await pilot.press("l")
        await pilot.pause()
        assert board._active_col == 1  # todo
        await pilot.press("l")
        await pilot.pause()
        # Should skip in_progress (empty) and in_review (empty) and
        # land on done (index 4).
        assert board._active_col == 4
        await fake_ws.close()


async def test_board_l_is_noop_when_no_columns_to_the_right(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    When every column to the right is empty, ``l`` stays put.
    """
    stories = [_story("story-1", "KAN-1", state="backlog")]
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
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

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        board = app.screen
        assert isinstance(board, BoardScreen)
        assert board._active_col == 0
        await pilot.press("l")
        await pilot.pause()
        assert board._active_col == 0
        # Sanity: backlog column still holds the single card.
        backlog = board.query_one("#col-backlog", BoardColumn)
        assert [c.story["human_id"] for c in backlog.cards] == ["KAN-1"]
        await fake_ws.close()


# ---------------------------------------------------------------------
# Item 9: emoji actor badges
# ---------------------------------------------------------------------


def test_actor_badge_returns_emoji_on_capable_terminal(monkeypatch):
    """
    On a TERM other than ``dumb`` or ``linux``, each known actor type
    renders the emoji glyph.
    """
    monkeypatch.setenv("TERM", "xterm-256color")
    for actor_type, glyph in ACTOR_EMOJI.items():
        assert actor_badge(actor_type) == glyph
    assert actor_badge("unknown") == "?"


def test_actor_badge_falls_back_to_letter_on_dumb_terminal(monkeypatch):
    """
    ``TERM=dumb`` falls back to the single-letter label.
    """
    monkeypatch.setenv("TERM", "dumb")
    for actor_type, label in ACTOR_LABELS.items():
        assert actor_badge(actor_type) == label


def test_actor_badge_falls_back_on_linux_vt(monkeypatch):
    """
    ``TERM=linux`` (kernel VT) also triggers the fallback.
    """
    monkeypatch.setenv("TERM", "linux")
    assert not _terminal_supports_emoji()
    for actor_type, label in ACTOR_LABELS.items():
        assert actor_badge(actor_type) == label
