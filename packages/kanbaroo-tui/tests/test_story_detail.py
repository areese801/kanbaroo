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

from kanbaroo_tui.app import KanbarooTuiApp
from kanbaroo_tui.screens.board import BoardScreen
from kanbaroo_tui.screens.story_detail import StoryDetailScreen


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

    app = KanbarooTuiApp(
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

    app = KanbarooTuiApp(
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

    app = KanbarooTuiApp(
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


async def test_linkages_tab_renders_human_id_and_title(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Each linkage row on the Linkages tab shows the target's
    ``human_id "title"`` label, not just the UUID. Outgoing and
    incoming linkages both resolve the far end; a 404 on one
    linkage's target falls back to ``<uuid> (not accessible)``.
    """
    story_id = "story-1"
    linkages = [
        {
            "id": "link-1",
            "source_type": "story",
            "source_id": story_id,
            "target_type": "story",
            "target_id": "story-5",
            "link_type": "blocks",
            "created_at": "2026-04-18T00:00:00Z",
            "deleted_at": None,
        },
        {
            "id": "link-2",
            "source_type": "story",
            "source_id": story_id,
            "target_type": "story",
            "target_id": "story-gone",
            "link_type": "relates_to",
            "created_at": "2026-04-18T00:00:00Z",
            "deleted_at": None,
        },
        {
            "id": "link-3",
            "source_type": "story",
            "source_id": "story-7",
            "target_type": "story",
            "target_id": story_id,
            "link_type": "is_blocked_by",
            "created_at": "2026-04-18T00:00:00Z",
            "deleted_at": None,
        },
    ]
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
    mock_api.json(
        "GET",
        "/stories/story-1/linkages",
        body={"items": linkages, "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/stories/story-1/linkages",
        body={"items": linkages, "next_cursor": None},
    )
    # Resolve each linkage endpoint's story body. story-gone returns
    # 404 to exercise the "(not accessible)" fallback.
    mock_api.json(
        "GET",
        "/stories/story-5",
        body={
            "id": "story-5",
            "workspace_id": "ws-1",
            "epic_id": None,
            "human_id": "KAN-5",
            "title": "Try MCP from outer Claude",
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
        },
    )
    mock_api.add(
        "GET",
        "/stories/story-gone",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "gone"}},
        ),
    )
    mock_api.json(
        "GET",
        "/stories/story-7",
        body={
            "id": "story-7",
            "workspace_id": "ws-1",
            "epic_id": None,
            "human_id": "KAN-7",
            "title": "Blocker we need to land",
            "description": None,
            "priority": "none",
            "state": "todo",
            "state_actor_type": None,
            "state_actor_id": None,
            "branch_name": None,
            "commit_sha": None,
            "pr_url": None,
            "created_at": "2026-04-17T00:00:00Z",
            "updated_at": "2026-04-17T00:00:00Z",
            "deleted_at": None,
            "version": 1,
        },
    )
    mock_api.add(
        "GET",
        "/audit/entity/story/story-1",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "cage K"}},
        ),
    )
    mock_api.add(
        "GET",
        "/audit/entity/story/story-1",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "cage K"}},
        ),
    )

    app = KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await _open_detail(app, pilot)
        await pilot.press("3")
        await pilot.pause()
        await pilot.pause()
        detail = app.screen
        assert isinstance(detail, StoryDetailScreen)
        linkages_body = detail.query("#linkages-body Static")
        rendered = " ".join(str(s.render()) for s in linkages_body)
        assert "KAN-5" in rendered
        assert "Try MCP from outer Claude" in rendered
        assert "KAN-7" in rendered
        assert "Blocker we need to land" in rendered
        assert "not accessible" in rendered
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

    app = KanbarooTuiApp(
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


def _comment(
    *,
    id_: str,
    body: str,
    parent_id: str | None = None,
) -> dict:
    """
    Canned comment body.
    """
    return {
        "id": id_,
        "story_id": "story-1",
        "parent_id": parent_id,
        "body": body,
        "actor_type": "human",
        "actor_id": "adam",
        "created_at": "2026-04-18T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


async def test_reply_to_top_level_comment_posts_with_parent_id(
    mock_api, fake_ws, tui_config, client_factory, ws_factory, fake_editor
):
    """
    Pressing ``R`` (capital) with a top-level comment focused opens
    the editor and POSTs a reply with ``parent_id`` set to that
    comment's id.
    """
    top_level = _comment(id_="c-top", body="LGTM")
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
    # Initial story detail load: comments populated.
    story_body = _story()
    for _ in range(3):
        mock_api.add(
            "GET",
            "/stories/story-1",
            lambda _req, body=story_body: httpx.Response(
                200,
                json=body,
                headers={"ETag": str(body["version"])},
            ),
        )
    mock_api.json(
        "GET",
        "/stories/story-1/comments",
        body={"items": [top_level]},
    )
    mock_api.json(
        "GET",
        "/stories/story-1/comments",
        body={"items": [top_level]},
    )
    mock_api.json("GET", "/stories/story-1/linkages", body=_empty_list())
    mock_api.json("GET", "/stories/story-1/linkages", body=_empty_list())
    mock_api.add(
        "GET",
        "/audit/entity/story/story-1",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "cage K"}},
        ),
    )
    mock_api.add(
        "GET",
        "/audit/entity/story/story-1",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "cage K"}},
        ),
    )
    # Reply POST:
    reply_body = _comment(id_="c-reply", body="+1", parent_id="c-top")
    mock_api.add(
        "POST",
        "/stories/story-1/comments",
        lambda _req: httpx.Response(201, json=reply_body),
    )
    # Post-reply refresh routes:
    mock_api.json(
        "GET",
        "/stories/story-1/comments",
        body={"items": [top_level, reply_body]},
    )
    mock_api.json("GET", "/stories/story-1/linkages", body=_empty_list())
    mock_api.add(
        "GET",
        "/audit/entity/story/story-1",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "cage K"}},
        ),
    )
    fake_editor.content_to_write = "+1"

    app = KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
        editor_runner=fake_editor,
    )
    async with app.run_test() as pilot:
        await _open_detail(app, pilot)
        # Switch to the Comments tab and focus the only comment.
        await pilot.press("2")
        await pilot.pause()
        from kanbaroo_tui.screens.story_detail import CommentWidget

        comment_widget = app.screen.query(CommentWidget).first()
        assert comment_widget is not None
        comment_widget.focus()
        await pilot.pause()
        # R reply
        await pilot.press("R")
        await pilot.pause()
        await pilot.pause()

        post_requests = [
            r
            for r in mock_api.requests
            if r.method == "POST" and r.path == "/stories/story-1/comments"
        ]
        assert len(post_requests) == 1
        assert post_requests[0].body == {"body": "+1", "parent_id": "c-top"}
        await fake_ws.close()


async def test_reply_to_reply_is_rejected(
    mock_api, fake_ws, tui_config, client_factory, ws_factory, fake_editor
):
    """
    Pressing ``R`` on a reply comment (one that already has a
    ``parent_id``) flashes "cannot reply to a reply" and does not
    POST. Spec section 3.1: one-level threading.
    """
    top_level = _comment(id_="c-top", body="LGTM")
    reply = _comment(id_="c-reply", body="+1", parent_id="c-top")
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
    mock_api.json(
        "GET",
        "/stories/story-1/comments",
        body={"items": [top_level, reply]},
    )
    mock_api.json(
        "GET",
        "/stories/story-1/comments",
        body={"items": [top_level, reply]},
    )
    mock_api.json("GET", "/stories/story-1/linkages", body=_empty_list())
    mock_api.json("GET", "/stories/story-1/linkages", body=_empty_list())
    mock_api.add(
        "GET",
        "/audit/entity/story/story-1",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "cage K"}},
        ),
    )
    mock_api.add(
        "GET",
        "/audit/entity/story/story-1",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "cage K"}},
        ),
    )
    # Deliberately no POST route: if the action wrongly fires, the
    # MockApi's unknown-route assertion trips the test.
    fake_editor.content_to_write = "+1"

    app = KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
        editor_runner=fake_editor,
    )
    async with app.run_test() as pilot:
        await _open_detail(app, pilot)
        await pilot.press("2")
        await pilot.pause()
        from kanbaroo_tui.screens.story_detail import CommentWidget

        reply_widget = next(
            w for w in app.screen.query(CommentWidget) if w.comment["id"] == "c-reply"
        )
        reply_widget.focus()
        await pilot.pause()
        await pilot.press("R")
        await pilot.pause()
        await pilot.pause()
        posts = [
            r
            for r in mock_api.requests
            if r.method == "POST" and r.path == "/stories/story-1/comments"
        ]
        assert posts == []
        # Editor should never have been invoked (short-circuited before edit_markdown).
        assert fake_editor.invocations == []
        await fake_ws.close()


async def test_reply_without_focused_comment_no_ops(
    mock_api, fake_ws, tui_config, client_factory, ws_factory, fake_editor
):
    """
    Pressing ``R`` with no comment focused (e.g. Description tab
    active) flashes a hint and does nothing else.
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
    _seed_detail_routes(mock_api)
    fake_editor.content_to_write = "should never be written"

    app = KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
        editor_runner=fake_editor,
    )
    async with app.run_test() as pilot:
        await _open_detail(app, pilot)
        # Stay on Description tab; no comment widget can possibly hold
        # focus (there are no comments seeded either).
        await pilot.press("R")
        await pilot.pause()
        posts = [
            r
            for r in mock_api.requests
            if r.method == "POST" and r.path == "/stories/story-1/comments"
        ]
        assert posts == []
        assert fake_editor.invocations == []
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

    app = KanbarooTuiApp(
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
