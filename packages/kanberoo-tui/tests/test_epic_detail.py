"""
Tests for the epic detail screen (mini-board scoped to one epic).

Covers:

* Stories land in the column that matches their state.
* Move mode (``m`` then ``t``) transitions the focused card via
  ``POST /stories/{id}/transition`` with ``If-Match`` taken from a
  prior GET.
"""

from __future__ import annotations

from kanberoo_tui.app import KanberooTuiApp
from kanberoo_tui.screens.board import COLUMN_STATES
from kanberoo_tui.screens.epic_detail import EpicDetailScreen
from kanberoo_tui.screens.epic_list import EpicListScreen
from kanberoo_tui.widgets.board_column import BoardColumn


def _workspace_list_body(items):
    return {"items": items, "next_cursor": None}


def _empty_list():
    return {"items": [], "next_cursor": None}


def _workspace(id_="ws-1", key="KAN", name="Kanberoo"):
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


def _epic(id_="epic-1", human_id="KAN-2", title="First", workspace_id="ws-1"):
    return {
        "id": id_,
        "workspace_id": workspace_id,
        "human_id": human_id,
        "title": title,
        "description": None,
        "state": "open",
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
    epic_id="epic-1",
    workspace_id="ws-1",
    version=1,
):
    return {
        "id": id_,
        "workspace_id": workspace_id,
        "epic_id": epic_id,
        "human_id": human_id,
        "title": "story",
        "description": None,
        "priority": "none",
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


def _seed_landing(mock_api, epic_list):
    """
    Seed the workspace-list landing and the epic list that precedes
    the detail screen.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    # Workspace-list: count stories + epics.
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    # Epic list screen re-fetches the epic list.
    mock_api.json(
        "GET",
        "/workspaces/ws-1/epics",
        body={"items": epic_list, "next_cursor": None},
    )
    # Plus one story-count fetch per epic.
    for _ in epic_list:
        mock_api.json(
            "GET",
            "/workspaces/ws-1/stories",
            body=_empty_list(),
        )


async def _open_detail(mock_api, fake_ws, tui_config, client_factory, ws_factory):
    """
    Navigate workspace list -> epic list -> epic detail.
    """
    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    return app


async def test_epic_detail_places_stories_in_right_columns(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Each story lands in the column matching its state.
    """
    _seed_landing(mock_api, [_epic()])
    stories = [
        _story("story-1", "KAN-3", state="backlog"),
        _story("story-2", "KAN-4", state="todo"),
        _story("story-3", "KAN-6", state="in_progress"),
        _story("story-4", "KAN-7", state="done"),
    ]
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": stories, "next_cursor": None},
    )

    app = await _open_detail(mock_api, fake_ws, tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("E")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EpicListScreen)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EpicDetailScreen)
        for state_key, _ in COLUMN_STATES:
            column = screen.query_one(f"#epic-col-{state_key}", BoardColumn)
            human_ids = {c.story["human_id"] for c in column.cards}
            expected = {s["human_id"] for s in stories if s["state"] == state_key}
            assert human_ids == expected, (
                f"column {state_key}: {human_ids} != {expected}"
            )
        await fake_ws.close()


async def test_epic_detail_move_mode_transitions_story(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Move mode posts ``/stories/{id}/transition`` with ``If-Match``
    from a prior GET and the card ends up in the target column.
    """
    _seed_landing(mock_api, [_epic()])
    initial = [_story("story-1", "KAN-3", state="backlog", version=1)]
    moved = [_story("story-1", "KAN-3", state="todo", version=2)]
    # Epic detail initial fetch, then the post-transition refetch.
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

    app = await _open_detail(mock_api, fake_ws, tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("E")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EpicDetailScreen)

        await pilot.press("m")
        await pilot.pause()
        assert screen.move_mode is True
        await pilot.press("t")
        await pilot.pause()
        await pilot.pause()
        assert screen.move_mode is False

        backlog = screen.query_one("#epic-col-backlog", BoardColumn)
        todo = screen.query_one("#epic-col-todo", BoardColumn)
        assert [c.story["human_id"] for c in backlog.cards] == []
        assert [c.story["human_id"] for c in todo.cards] == ["KAN-3"]

        transitions = [
            r for r in mock_api.requests if r.path == "/stories/story-1/transition"
        ]
        assert len(transitions) == 1
        assert transitions[0].method == "POST"
        assert transitions[0].body == {"to_state": "todo"}
        assert transitions[0].headers.get("if-match") == "1"
        await fake_ws.close()
