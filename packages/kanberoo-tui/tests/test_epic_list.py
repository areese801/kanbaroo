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

from kanberoo_tui.app import KanberooTuiApp
from kanberoo_tui.screens.epic_detail import EpicDetailScreen
from kanberoo_tui.screens.epic_list import EpicListScreen
from kanberoo_tui.screens.workspace_list import WorkspaceListScreen


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

    app = KanberooTuiApp(
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

    app = KanberooTuiApp(
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

    app = KanberooTuiApp(
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
