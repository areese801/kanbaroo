"""
Tests for the story detail screen.

Exercises the five tabs (including 404 tolerance on the per-entity
audit endpoint), the ``e`` description-edit flow, and the ``c``
comment flow. Navigation is driven the same way cage H drives it:
start the app, press ``enter`` on the workspace list to reach the
board, then press ``enter`` on the focused card to push the detail
screen.
"""

from __future__ import annotations

import httpx

from kanberoo_tui.app import KanberooTuiApp
from kanberoo_tui.screens.board import BoardScreen
from kanberoo_tui.screens.story_detail import StoryDetailScreen


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


def _story(description: str | None = "Initial body", version: int = 1):
    return {
        "id": "story-1",
        "workspace_id": "ws-1",
        "epic_id": None,
        "human_id": "KAN-1",
        "title": "A story",
        "description": description,
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
        "version": version,
    }


def _seed_detail_routes(mock_api, *, story=None, extra_story_fetches: int = 1):
    """
    Register REST routes for the initial detail fetch.

    Cage H already registers the workspace-list route; this helper
    tops off with the routes the detail screen hits on mount. Story
    handlers are replayed ``extra_story_fetches + 1`` times so refresh
    cycles after mutations do not starve on the same route.
    """
    story = story or _story()
    for _ in range(extra_story_fetches + 1):
        mock_api.add(
            "GET",
            "/stories/story-1",
            lambda _req, body=story: httpx.Response(
                200,
                json=body,
                headers={"ETag": str(body["version"])},
            ),
        )
    mock_api.json("GET", "/stories/story-1/comments", body=_empty_list())
    mock_api.json("GET", "/stories/story-1/comments", body=_empty_list())
    mock_api.json("GET", "/stories/story-1/linkages", body=_empty_list())
    mock_api.json("GET", "/stories/story-1/linkages", body=_empty_list())
    # Audit endpoint is cage K's work; 404 should render an empty state.
    mock_api.add(
        "GET",
        "/audit/entity/story/story-1",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "not here yet"}},
        ),
    )
    mock_api.add(
        "GET",
        "/audit/entity/story/story-1",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "not here yet"}},
        ),
    )


async def _open_detail(app, pilot):
    """
    Drive the app from landing -> board -> detail by pressing enter
    twice. The board screen requires two pauses for the mount-and-
    fetch cycle before the card is focusable; detail needs one more
    for the tabs to populate.
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


async def test_story_detail_renders_with_audit_404(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story()], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story()], "next_cursor": None},
    )
    _seed_detail_routes(mock_api)

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await _open_detail(app, pilot)
        detail = app.screen
        assert isinstance(detail, StoryDetailScreen)
        assert detail.story["human_id"] == "KAN-1"
        # The 404 should have flipped the unavailable flag; no error
        # notifications should have surfaced because 404 is expected.
        audit_requests = [
            r for r in mock_api.requests if r.path == "/audit/entity/story/story-1"
        ]
        assert len(audit_requests) == 1
        await fake_ws.close()


async def test_edit_description_issues_patch_with_if_match(
    mock_api, fake_ws, tui_config, client_factory, ws_factory, fake_editor
):
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story()], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story()], "next_cursor": None},
    )
    _seed_detail_routes(mock_api)
    patched_story = _story(description="edited content", version=2)
    mock_api.add(
        "PATCH",
        "/stories/story-1",
        lambda _req: httpx.Response(
            200,
            json=patched_story,
            headers={"ETag": "2"},
        ),
    )
    fake_editor.content_to_write = "edited content"

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
        editor_runner=fake_editor,
    )
    async with app.run_test() as pilot:
        await _open_detail(app, pilot)
        await pilot.press("e")
        await pilot.pause()
        await pilot.pause()

        patch_requests = [
            r
            for r in mock_api.requests
            if r.method == "PATCH" and r.path == "/stories/story-1"
        ]
        assert len(patch_requests) == 1
        patch = patch_requests[0]
        assert patch.body == {"description": "edited content"}
        assert patch.headers.get("if-match") == "1"
        assert app.screen.story["description"] == "edited content"
        assert app.screen.story["version"] == 2
        assert len(fake_editor.invocations) == 1
        await fake_ws.close()


async def test_add_comment_posts_when_non_empty(
    mock_api, fake_ws, tui_config, client_factory, ws_factory, fake_editor
):
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story()], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story()], "next_cursor": None},
    )
    # First load of the detail screen: initial routes.
    _seed_detail_routes(mock_api, extra_story_fetches=2)
    new_comment = {
        "id": "c-1",
        "story_id": "story-1",
        "parent_id": None,
        "body": "LGTM",
        "actor_type": "human",
        "actor_id": "adam",
        "created_at": "2026-04-18T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }
    mock_api.add(
        "POST",
        "/stories/story-1/comments",
        lambda _req: httpx.Response(201, json=new_comment),
    )
    # The post-comment refresh will consume one more round of tab
    # fetches. Register those.
    mock_api.json(
        "GET",
        "/stories/story-1/comments",
        body={"items": [new_comment]},
    )
    mock_api.json("GET", "/stories/story-1/linkages", body=_empty_list())
    mock_api.add(
        "GET",
        "/audit/entity/story/story-1",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "not here yet"}},
        ),
    )
    fake_editor.content_to_write = "LGTM"

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
        editor_runner=fake_editor,
    )
    async with app.run_test() as pilot:
        await _open_detail(app, pilot)
        await pilot.press("c")
        await pilot.pause()
        await pilot.pause()
        post_requests = [
            r
            for r in mock_api.requests
            if r.method == "POST" and r.path == "/stories/story-1/comments"
        ]
        assert len(post_requests) == 1
        assert post_requests[0].body == {"body": "LGTM"}
        await fake_ws.close()


async def test_audit_tab_renders_state_transition(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    A ``state_changed`` audit row on the Audit tab surfaces the
    ``before -> after`` states prominently rather than burying them in
    the raw diff.
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
        body={"items": [_story()], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story()], "next_cursor": None},
    )
    # Story, comments, linkages routes used on detail mount.
    story_body = _story()
    for _ in range(2):
        mock_api.add(
            "GET",
            "/stories/story-1",
            lambda _req, body=story_body: httpx.Response(
                200,
                json=body,
                headers={"ETag": str(body["version"])},
            ),
        )
    mock_api.json("GET", "/stories/story-1/comments", body=_empty_list())
    mock_api.json("GET", "/stories/story-1/comments", body=_empty_list())
    mock_api.json("GET", "/stories/story-1/linkages", body=_empty_list())
    mock_api.json("GET", "/stories/story-1/linkages", body=_empty_list())
    audit_row = {
        "id": "evt-42",
        "occurred_at": "2026-04-18T03:00:00Z",
        "actor_type": "claude",
        "actor_id": "outer-claude",
        "entity_type": "story",
        "entity_id": "story-1",
        "action": "state_changed",
        "diff": {
            "before": {"state": "todo"},
            "after": {"state": "in_progress"},
        },
    }
    mock_api.json(
        "GET",
        "/audit/entity/story/story-1",
        body={"items": [audit_row], "next_cursor": None},
    )

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await _open_detail(app, pilot)
        detail = app.screen
        assert isinstance(detail, StoryDetailScreen)
        audit_body = detail.query("#audit-body Static")
        rendered = " ".join(str(s.content) for s in audit_body)
        assert "todo" in rendered
        assert "in_progress" in rendered
        assert "\u2192" in rendered
        await fake_ws.close()


async def test_add_comment_aborts_when_empty(
    mock_api, fake_ws, tui_config, client_factory, ws_factory, fake_editor
):
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story()], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": [_story()], "next_cursor": None},
    )
    _seed_detail_routes(mock_api)
    # Do not register a POST route: if the test logic is wrong and the
    # helper tries to POST, MockApi will raise.
    fake_editor.content_to_write = None  # no change, so edit returns None

    app = KanberooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
        editor_runner=fake_editor,
    )
    async with app.run_test() as pilot:
        await _open_detail(app, pilot)
        await pilot.press("c")
        await pilot.pause()
        await pilot.pause()
        post_requests = [
            r
            for r in mock_api.requests
            if r.method == "POST" and r.path == "/stories/story-1/comments"
        ]
        assert post_requests == []
        await fake_ws.close()
