"""
Tests for the duplicate-title confirmation modal that runs between
the new-story editor and the create POST.

Two scenarios:

* The similar endpoint returns a non-empty list, the confirm modal
  appears, the user cancels it, no POST is sent.
* The similar endpoint returns a non-empty list, the user confirms
  it, the POST runs and the board refetches.
"""

from __future__ import annotations

import httpx

from kanbaroo_tui.app import KanbarooTuiApp
from kanbaroo_tui.screens.board import BoardScreen
from kanbaroo_tui.widgets.duplicate_confirm import DuplicateConfirm


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


async def test_new_story_with_similar_cancels_via_modal(
    mock_api, fake_ws, tui_config, client_factory, ws_factory, fake_editor
):
    """
    A non-empty ``stories/similar`` response opens the confirm modal;
    pressing ``n`` dismisses it without a POST.
    """
    mock_api.json(
        "GET", "/workspaces", body={"items": [_workspace()], "next_cursor": None}
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories/similar",
        body={
            "items": [_story("story-1", "KAN-1", title="My new story")],
            "next_cursor": None,
        },
    )
    fake_editor.content_to_write = "# My new story\n\nSome description text.\n"

    app = KanbarooTuiApp(
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
        assert isinstance(app.screen, DuplicateConfirm)

        await pilot.press("n")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, BoardScreen)

        creates = [
            r
            for r in mock_api.requests
            if r.method == "POST" and r.path == "/workspaces/ws-1/stories"
        ]
        assert creates == []
        await fake_ws.close()


async def test_new_story_with_similar_proceeds_when_confirmed(
    mock_api, fake_ws, tui_config, client_factory, ws_factory, fake_editor
):
    """
    Confirming the modal with ``y`` proceeds with the create.
    """
    mock_api.json(
        "GET", "/workspaces", body={"items": [_workspace()], "next_cursor": None}
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    # Final refetch shows the new card.
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={
            "items": [_story("story-99", "KAN-99", title="My new story")],
            "next_cursor": None,
        },
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories/similar",
        body={
            "items": [_story("story-1", "KAN-1", title="My new story")],
            "next_cursor": None,
        },
    )
    new_story = _story("story-99", "KAN-99", title="My new story")
    mock_api.add(
        "POST",
        "/workspaces/ws-1/stories",
        lambda _req: httpx.Response(201, json=new_story),
    )
    fake_editor.content_to_write = "# My new story\n\nSome description text.\n"

    app = KanbarooTuiApp(
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
        assert isinstance(app.screen, DuplicateConfirm)

        await pilot.press("y")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, BoardScreen)

        creates = [
            r
            for r in mock_api.requests
            if r.method == "POST" and r.path == "/workspaces/ws-1/stories"
        ]
        assert len(creates) == 1
        await fake_ws.close()
