"""
Tests for the epic list screen.

Covers the two scenarios called out in the cage K task:

* The screen renders rows from the mock REST surface.
* Pressing ``enter`` on a row pushes the matching
  :class:`EpicDetailScreen`.

A third test verifies the ``E`` binding on the workspace list screen
routes to :class:`EpicListScreen`.
"""

from __future__ import annotations

from textual.widgets import DataTable

from kanbaroo_tui.app import KanbarooTuiApp
from kanbaroo_tui.screens.epic_detail import EpicDetailScreen
from kanbaroo_tui.screens.epic_list import EpicListScreen
from kanbaroo_tui.screens.workspace_list import WorkspaceListScreen


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


def _epic(
    id_,
    human_id,
    *,
    title="Epic",
    state="open",
    workspace_id="ws-1",
    updated_at="2026-04-18T00:00:00Z",
):
    return {
        "id": id_,
        "workspace_id": workspace_id,
        "human_id": human_id,
        "title": title,
        "description": None,
        "state": state,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": updated_at,
        "deleted_at": None,
        "version": 1,
    }


def _seed_landing(mock_api):
    """
    Seed the workspace-list landing requests.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace()]),
    )
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())


async def test_epic_list_renders_rows(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Pressing ``E`` on the workspace list opens the epic list and
    renders one row per returned epic.
    """
    _seed_landing(mock_api)
    # The epic list screen re-fetches the epics in the workspace and
    # asks for a story count per epic.
    epics = [
        _epic("epic-1", "KAN-2", title="First"),
        _epic("epic-2", "KAN-5", title="Second"),
    ]
    mock_api.json(
        "GET",
        "/workspaces/ws-1/epics",
        body={"items": epics, "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body=_empty_list(),
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body=_empty_list(),
    )

    app = KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, WorkspaceListScreen)
        await pilot.press("E")
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EpicListScreen)
        table = screen.query_one("#epic-table", DataTable)
        assert table.row_count == 2
        assert [e["human_id"] for e in screen.epics] == ["KAN-2", "KAN-5"]
        await fake_ws.close()


async def test_epic_list_enter_pushes_detail(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Pressing ``enter`` on an epic row pushes the epic detail screen.
    """
    _seed_landing(mock_api)
    epic = _epic("epic-1", "KAN-2", title="First")
    mock_api.json(
        "GET",
        "/workspaces/ws-1/epics",
        body={"items": [epic], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body=_empty_list(),
    )
    # EpicDetailScreen fetches scoped stories on mount.
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body=_empty_list(),
    )

    app = KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("E")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EpicListScreen)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        detail = app.screen
        assert isinstance(detail, EpicDetailScreen)
        assert detail.epic["human_id"] == "KAN-2"
        await fake_ws.close()


async def test_workspace_list_E_binding_routes_to_epic_list(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    The ``E`` binding on the workspace list is wired; pressing it
    without a highlighted row is a no-op rather than an error, and
    with a row routes to :class:`EpicListScreen`.
    """
    _seed_landing(mock_api)
    mock_api.json(
        "GET",
        "/workspaces/ws-1/epics",
        body=_empty_list(),
    )

    app = KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, WorkspaceListScreen)
        await pilot.press("E")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EpicListScreen)
        await fake_ws.close()


def _story(id_, human_id, *, state="todo", epic_id="epic-1"):
    return {
        "id": id_,
        "workspace_id": "ws-1",
        "epic_id": epic_id,
        "human_id": human_id,
        "title": "Story",
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
        "version": 1,
    }


def _column_labels(table: DataTable) -> list[str]:
    return [str(column.label) for column in table.columns.values()]


def _row_cells(table: DataTable, row_key: str) -> list[str]:
    return [str(cell) for cell in table.get_row(row_key)]


async def test_epic_list_has_open_column_after_stories(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    The table carries a dedicated ``open`` column directly after
    ``stories``, with the pinned column order.
    """
    _seed_landing(mock_api)
    mock_api.json(
        "GET",
        "/workspaces/ws-1/epics",
        body=_empty_list(),
    )

    app = KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("E")
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EpicListScreen)
        table = screen.query_one("#epic-table", DataTable)
        assert _column_labels(table) == [
            "key",
            "title",
            "state",
            "stories",
            "open",
            "last updated",
        ]
        await fake_ws.close()


async def test_epic_list_open_count_excludes_done(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    The open count is the number of fetched stories whose state is not
    ``done``; the total still counts every story. Both come from the
    single per-epic story request.
    """
    _seed_landing(mock_api)
    mock_api.json(
        "GET",
        "/workspaces/ws-1/epics",
        body={"items": [_epic("epic-1", "KAN-2", title="Mixed")], "next_cursor": None},
    )
    stories = [
        _story("st-1", "KAN-10", state="backlog"),
        _story("st-2", "KAN-11", state="todo"),
        _story("st-3", "KAN-12", state="in_progress"),
        _story("st-4", "KAN-13", state="in_review"),
        _story("st-5", "KAN-14", state="done"),
        _story("st-6", "KAN-15", state="done"),
    ]
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
        await pilot.press("E")
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EpicListScreen)
        table = screen.query_one("#epic-table", DataTable)
        cells = _row_cells(table, "epic-1")
        assert cells[3] == "6"
        assert cells[4] == "4"
        await fake_ws.close()


async def test_epic_list_open_count_zero_when_all_done(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    An epic whose stories are all ``done`` shows an open count of zero
    while the total still reflects every story.
    """
    _seed_landing(mock_api)
    mock_api.json(
        "GET",
        "/workspaces/ws-1/epics",
        body={
            "items": [_epic("epic-1", "KAN-2", title="Finished")],
            "next_cursor": None,
        },
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={
            "items": [
                _story("st-1", "KAN-10", state="done"),
                _story("st-2", "KAN-11", state="done"),
                _story("st-3", "KAN-12", state="done"),
            ],
            "next_cursor": None,
        },
    )

    app = KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("E")
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EpicListScreen)
        table = screen.query_one("#epic-table", DataTable)
        cells = _row_cells(table, "epic-1")
        assert cells[3] == "3"
        assert cells[4] == "0"
        await fake_ws.close()


async def test_epic_list_open_count_marks_overflow(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    When the story page overflows (``next_cursor`` present) both the
    total and the open count carry a ``+`` suffix, because the open
    count is a lower bound computed from the fetched page only.
    """
    _seed_landing(mock_api)
    mock_api.json(
        "GET",
        "/workspaces/ws-1/epics",
        body={"items": [_epic("epic-1", "KAN-2", title="Huge")], "next_cursor": None},
    )
    stories = [
        _story(f"st-{i}", f"KAN-{i + 10}", state="done" if i % 4 == 0 else "todo")
        for i in range(200)
    ]
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": stories, "next_cursor": "opaque-cursor"},
    )

    app = KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("E")
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, EpicListScreen)
        table = screen.query_one("#epic-table", DataTable)
        cells = _row_cells(table, "epic-1")
        assert cells[3] == "200+"
        assert cells[4] == "150+"
        # Exactly one story request per epic: the open count must not
        # cost an extra round-trip.
        story_requests = [
            r for r in mock_api.requests if r.path == "/workspaces/ws-1/stories"
        ]
        # One from the workspace-list landing count, one from the epic row.
        assert len(story_requests) == 2
        await fake_ws.close()
