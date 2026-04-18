"""
Tests for the workspace list screen.
"""

from __future__ import annotations

from textual.widgets import DataTable

from kanberoo_tui.app import KanberooTuiApp
from kanberoo_tui.screens.board import BoardScreen
from kanberoo_tui.screens.workspace_list import WorkspaceListScreen


def _workspace_list_body(items):
    return {"items": items, "next_cursor": None}


def _empty_list():
    return {"items": [], "next_cursor": None}


def _workspace(id_, key, name, *, updated_at="2026-04-18T00:00:00Z"):
    return {
        "id": id_,
        "key": key,
        "name": name,
        "description": None,
        "next_issue_num": 1,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": updated_at,
        "deleted_at": None,
        "version": 1,
    }


async def test_workspace_list_renders_rows(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body(
            [
                _workspace("ws-1", "KAN", "Kanberoo"),
                _workspace("ws-2", "ENG", "Engineering"),
            ]
        ),
    )
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-2/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-2/epics", body=_empty_list())

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, WorkspaceListScreen)
        assert [ws["key"] for ws in screen.workspaces] == ["KAN", "ENG"]
        table = screen.query_one("#ws-table", DataTable)
        assert table.row_count == 2
        # First row is selected by default.
        await pilot.press("j")
        await pilot.pause()
        assert table.cursor_row == 1
        await pilot.press("k")
        await pilot.pause()
        assert table.cursor_row == 0
        await fake_ws.close()


async def test_enter_pushes_board(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace("ws-1", "KAN", "Kanberoo")]),
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
        assert isinstance(app.screen, WorkspaceListScreen)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, BoardScreen)
        assert app.screen.workspace["key"] == "KAN"
        await fake_ws.close()


async def test_workspace_event_triggers_refetch(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    mock_api.json(
        "GET",
        "/workspaces",
        body=_workspace_list_body([_workspace("ws-1", "KAN", "Kanberoo")]),
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
        screen = app.screen
        assert isinstance(screen, WorkspaceListScreen)
        initial = sum(1 for r in mock_api.requests if r.path == "/workspaces")
        assert initial == 1
        await fake_ws.push(
            {
                "event_id": "evt-1",
                "event_type": "workspace.updated",
                "occurred_at": "2026-04-18T01:00:00Z",
                "actor_type": "human",
                "actor_id": "adam",
                "entity_type": "workspace",
                "entity_id": "ws-1",
                "entity_version": 2,
                "payload": {},
            }
        )
        await pilot.pause()
        await pilot.pause()
        after = sum(1 for r in mock_api.requests if r.path == "/workspaces")
        assert after == 2
        await fake_ws.close()
