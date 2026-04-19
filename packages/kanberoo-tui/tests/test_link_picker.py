"""
Tests for the :class:`LinkPicker` modal on the story detail screen.

Covers the target-resolution UX added in cage delta: typing a human
id and pressing enter shows the resolved title below the input; a
bogus id surfaces a "not found" hint; attempting to submit before
resolving bails without POSTing a bogus linkage.
"""

from __future__ import annotations

import httpx
from textual.widgets import Input, OptionList, Static

from kanberoo_tui.app import KanberooTuiApp
from kanberoo_tui.screens.story_detail import StoryDetailScreen
from kanberoo_tui.widgets.link_picker import LinkPicker


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


def _story_body(
    *, story_id: str = "story-1", human_id: str = "KAN-1", title: str = "A story"
):
    return {
        "id": story_id,
        "workspace_id": "ws-1",
        "epic_id": None,
        "human_id": human_id,
        "title": title,
        "description": None,
        "priority": "none",
        "state": "backlog",
        "state_actor_type": "human",
        "state_actor_id": "adam",
        "branch_name": None,
        "commit_sha": None,
        "pr_url": None,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": "2026-04-17T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def _seed_detail(mock_api, *, story=None, extras=1):
    """
    Seed the routes the detail screen hits on mount and refresh.

    ``extras`` controls how many refresh cycles we allow before the
    handlers stop matching; one refresh is enough for the link-picker
    tests (no refetch is triggered after the modal is pushed).
    """
    story = story or _story_body()
    for _ in range(extras + 1):
        mock_api.add(
            "GET",
            "/stories/story-1",
            lambda _req, body=story: httpx.Response(
                200, json=body, headers={"ETag": str(body["version"])}
            ),
        )
    mock_api.json("GET", "/stories/story-1/comments", body=_empty_list())
    mock_api.json("GET", "/stories/story-1/comments", body=_empty_list())
    mock_api.json("GET", "/stories/story-1/linkages", body=_empty_list())
    mock_api.json("GET", "/stories/story-1/linkages", body=_empty_list())
    mock_api.add(
        "GET",
        "/audit/entity/story/story-1",
        lambda _req: httpx.Response(
            404, json={"error": {"code": "not_found", "message": "cage K"}}
        ),
    )
    mock_api.add(
        "GET",
        "/audit/entity/story/story-1",
        lambda _req: httpx.Response(
            404, json={"error": {"code": "not_found", "message": "cage K"}}
        ),
    )


async def _open_picker(app, pilot):
    """
    Navigate workspace list -> board -> detail, then press ``L``.
    """
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()
    assert isinstance(app.screen, StoryDetailScreen)
    await pilot.press("L")
    await pilot.pause()
    await pilot.pause()
    assert isinstance(app.screen, LinkPicker)


async def test_link_picker_resolves_target_on_input_submit(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Typing a valid human id into the Input and pressing enter
    resolves the target and shows its title in the preview row.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story_body()], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story_body()], "next_cursor": None},
    )
    _seed_detail(mock_api)
    # Target resolution: KAN-5 resolves to story-5.
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-5",
        body=_story_body(
            story_id="story-5",
            human_id="KAN-5",
            title="Try MCP from outer Claude",
        ),
    )

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await _open_picker(app, pilot)
        modal = app.screen
        assert isinstance(modal, LinkPicker)
        target_input = modal.query_one("#link-target", Input)
        target_input.value = "KAN-5"
        # Simulate Enter in the input, which fires on_input_submitted.
        await target_input.action_submit()
        await pilot.pause()
        await pilot.pause()
        preview = modal.query_one("#link-target-resolved", Static)
        rendered = str(preview.render())
        assert "KAN-5" in rendered
        assert "Try MCP from outer Claude" in rendered
        await fake_ws.close()


async def test_link_picker_shows_not_found_for_bogus_id(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    A bogus human id surfaces "not found" in the preview and leaves
    the resolved-target cache empty.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story_body()], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story_body()], "next_cursor": None},
    )
    _seed_detail(mock_api)
    mock_api.add(
        "GET",
        "/stories/by-key/KAN-999",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "story not found"}},
        ),
    )

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await _open_picker(app, pilot)
        modal = app.screen
        assert isinstance(modal, LinkPicker)
        target_input = modal.query_one("#link-target", Input)
        target_input.value = "KAN-999"
        await target_input.action_submit()
        await pilot.pause()
        await pilot.pause()
        preview = modal.query_one("#link-target-resolved", Static)
        assert "not found" in str(preview.render()).lower()
        assert modal._resolved_target is None
        await fake_ws.close()


async def test_link_picker_submit_blocked_until_resolved(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Pressing ``ctrl+s`` before the target is resolved does not POST a
    linkage: the modal flashes a nudge and stays open. Regression
    guard for posting against bogus ids.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story_body()], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story_body()], "next_cursor": None},
    )
    _seed_detail(mock_api)

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await _open_picker(app, pilot)
        modal = app.screen
        assert isinstance(modal, LinkPicker)
        # Pick a link type (without the cursor hovering on it the
        # submit bails on that check first).
        option_list = modal.query_one("#link-type", OptionList)
        option_list.highlighted = 0
        # Submit without resolving the target first.
        await modal.action_submit()
        await pilot.pause()
        posts = [
            r for r in mock_api.requests if r.method == "POST" and r.path == "/linkages"
        ]
        assert posts == []
        # Modal stays up.
        assert isinstance(app.screen, LinkPicker)
        await fake_ws.close()
