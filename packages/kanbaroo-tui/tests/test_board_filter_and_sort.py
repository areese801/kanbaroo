"""
Tests for the new tag-filter (``f``/``F``) and priority-sort (``s``)
keybindings on the board screen.

Filter scenario:
* Workspace seeded with two tagged stories and one untagged.
* Pressing ``f`` opens the picker; toggling one tag and pressing
  enter restricts the board to that tag's stories.
* Pressing ``F`` clears the filter and the untagged story comes back.

Sort scenario:
* Column seeded with four stories of different priorities.
* Pressing ``s`` cycles to ``priority-desc`` and the column reorders.
* Pressing ``s`` again returns to ``id-asc`` (ascending).
"""

from __future__ import annotations

from kanbaroo_tui.app import KanbarooTuiApp
from kanbaroo_tui.screens.board import (
    SORT_MODE_ID_ASC,
    SORT_MODE_PRIORITY_DESC,
    BoardScreen,
    sort_stories,
)
from kanbaroo_tui.widgets.board_column import BoardColumn
from kanbaroo_tui.widgets.tag_filter import TagFilterPicker


def _empty_list():
    return {"items": [], "next_cursor": None}


def _workspace():
    return {
        "id": "ws-1",
        "key": "KAN",
        "name": "Kanbaroo",
        "description": None,
        "next_issue_num": 1,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": "2026-04-17T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def _story(id_, human_id, *, state="backlog", priority="none", title="A"):
    return {
        "id": id_,
        "workspace_id": "ws-1",
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
        "version": 1,
    }


def _tag(id_, name):
    return {
        "id": id_,
        "workspace_id": "ws-1",
        "name": name,
        "color": None,
        "created_at": "2026-04-17T00:00:00Z",
        "deleted_at": None,
    }


def test_sort_stories_priority_then_id() -> None:
    """
    Priority mode orders high before medium before low before none,
    breaking ties on the numeric id suffix ascending.
    """
    stories = [
        _story("a", "KAN-3", priority="low"),
        _story("b", "KAN-2", priority="high"),
        _story("c", "KAN-4", priority="none"),
        _story("d", "KAN-1", priority="high"),
        _story("e", "KAN-5", priority="medium"),
    ]
    ordered = sort_stories(stories, SORT_MODE_PRIORITY_DESC)
    assert [s["human_id"] for s in ordered] == [
        "KAN-1",
        "KAN-2",
        "KAN-5",
        "KAN-3",
        "KAN-4",
    ]


def test_sort_stories_id_asc() -> None:
    """
    The default mode sorts by numeric id suffix ascending so KAN-2
    precedes KAN-10.
    """
    stories = [
        _story("a", "KAN-10", priority="none"),
        _story("b", "KAN-2", priority="none"),
    ]
    ordered = sort_stories(stories, SORT_MODE_ID_ASC)
    assert [s["human_id"] for s in ordered] == ["KAN-2", "KAN-10"]


async def test_board_tag_filter_apply_and_clear(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Pressing ``f``, toggling one tag, and applying restricts the
    board to stories carrying that tag. Pressing ``F`` restores the
    full set.
    """
    tagged_a = _story("story-a", "KAN-1", title="tagged a")
    tagged_b = _story("story-b", "KAN-2", title="tagged b")
    untagged = _story("story-c", "KAN-3", title="untagged")
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    # Workspace-list count + initial board fetch + filtered fetch +
    # clear-filter refetch. FIFO handlers get consumed in order.
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [tagged_a, tagged_b, untagged], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [tagged_a, tagged_b, untagged], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/tags",
        body={"items": [_tag("tag-bug", "bug"), _tag("tag-fe", "frontend")]},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [tagged_a, tagged_b], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [tagged_a, tagged_b, untagged], "next_cursor": None},
    )

    app = KanbarooTuiApp(
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
        backlog = board.query_one("#col-backlog", BoardColumn)
        assert {c.story["human_id"] for c in backlog.cards} == {
            "KAN-1",
            "KAN-2",
            "KAN-3",
        }

        await pilot.press("f")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, TagFilterPicker)
        # Tick the first option ("bug").
        await pilot.press("space")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, BoardScreen)
        assert board.active_tag_filter == [("tag-bug", "bug")]
        backlog = board.query_one("#col-backlog", BoardColumn)
        assert {c.story["human_id"] for c in backlog.cards} == {"KAN-1", "KAN-2"}

        await pilot.press("F")
        await pilot.pause()
        await pilot.pause()
        assert board.active_tag_filter == []
        backlog = board.query_one("#col-backlog", BoardColumn)
        assert {c.story["human_id"] for c in backlog.cards} == {
            "KAN-1",
            "KAN-2",
            "KAN-3",
        }
        await fake_ws.close()


async def test_board_priority_sort_toggle(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Pressing ``s`` cycles the column ordering to priority mode and
    pressing it again returns to id-asc.
    """
    stories = [
        _story("a", "KAN-1", priority="low"),
        _story("b", "KAN-2", priority="high"),
        _story("c", "KAN-3", priority="medium"),
        _story("d", "KAN-4", priority="none"),
    ]
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    # Workspace-list count + initial board fetch use the same single
    # registered handler when only one is provided.
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": stories, "next_cursor": None},
    )

    app = KanbarooTuiApp(
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
        backlog = board.query_one("#col-backlog", BoardColumn)
        assert [c.story["human_id"] for c in backlog.cards] == [
            "KAN-1",
            "KAN-2",
            "KAN-3",
            "KAN-4",
        ]

        await pilot.press("s")
        await pilot.pause()
        assert board.sort_mode == SORT_MODE_PRIORITY_DESC
        backlog = board.query_one("#col-backlog", BoardColumn)
        assert [c.story["human_id"] for c in backlog.cards] == [
            "KAN-2",
            "KAN-3",
            "KAN-1",
            "KAN-4",
        ]

        await pilot.press("s")
        await pilot.pause()
        assert board.sort_mode == SORT_MODE_ID_ASC
        backlog = board.query_one("#col-backlog", BoardColumn)
        assert [c.story["human_id"] for c in backlog.cards] == [
            "KAN-1",
            "KAN-2",
            "KAN-3",
            "KAN-4",
        ]
        await fake_ws.close()
