"""
Tests for the global fuzzy-search overlay.

Two scenarios:

* Typing in the input narrows the results table and only the
  matching story remains above the score threshold.
* Pressing ``enter`` on a highlighted result pushes the story detail
  screen for that story.
"""

from __future__ import annotations

import httpx

from kanbaroo_tui.app import KanbarooTuiApp
from kanbaroo_tui.screens.search import IndexedStory, SearchScreen, _score
from kanbaroo_tui.screens.story_detail import StoryDetailScreen
from kanbaroo_tui.screens.workspace_list import WorkspaceListScreen


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


def _story(id_, human_id, title, description: str | None = None, version: int = 1):
    return {
        "id": id_,
        "workspace_id": "ws-1",
        "epic_id": None,
        "human_id": human_id,
        "title": title,
        "description": description,
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
        "version": version,
    }


async def test_search_narrows_results_by_query(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    stories = [
        _story("s-1", "KAN-1", "authentication token rotation"),
        _story("s-2", "KAN-2", "fix markdown rendering bug"),
        _story("s-3", "KAN-3", "audit feed refresh"),
    ]
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    # The search index also walks /workspaces and /stories. Register
    # enough replays.
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": stories, "next_cursor": None},
    )
    for story in stories:
        mock_api.json("GET", f"/stories/{story['id']}/comments", body=_empty_list())

    app = KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, WorkspaceListScreen)
        await pilot.press("slash")
        await pilot.pause()
        await pilot.pause()
        search = app.screen
        assert isinstance(search, SearchScreen)
        assert len(search.index) == 3

        # Empty query shows every entry.
        assert len(search.ranked) == 3

        await pilot.press("a", "u", "d", "i", "t")
        await pilot.pause()
        await pilot.pause()
        human_ids = [entry.human_id for entry in search.ranked]
        # "audit feed refresh" should rank first.
        assert human_ids[0] == "KAN-3"
        await fake_ws.close()


async def test_search_matches_via_comment_body(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    A story whose only signal is in a comment body still appears in
    the search results when queried by a substring of that comment.
    """
    stories = [
        _story("s-1", "KAN-1", "Standalone title"),
        _story("s-2", "KAN-2", "Another story"),
    ]
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": stories, "next_cursor": None},
    )
    # Only s-1 has a comment matching the query.
    mock_api.json(
        "GET",
        "/stories/s-1/comments",
        body={
            "items": [
                {
                    "id": "c-1",
                    "story_id": "s-1",
                    "parent_id": None,
                    "body": "deployment pipeline broke when migrating",
                    "actor_type": "human",
                    "actor_id": "adam",
                    "created_at": "2026-04-17T00:00:00Z",
                    "updated_at": "2026-04-17T00:00:00Z",
                    "deleted_at": None,
                    "version": 1,
                }
            ],
            "next_cursor": None,
        },
    )
    mock_api.json("GET", "/stories/s-2/comments", body=_empty_list())

    app = KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.pause()
        search = app.screen
        assert isinstance(search, SearchScreen)
        await pilot.press(*list("deployment"))
        await pilot.pause()
        await pilot.pause()
        human_ids = [entry.human_id for entry in search.ranked]
        assert "KAN-1" in human_ids
        # The story whose only match is a comment should rank
        # above the story with no signal.
        assert human_ids[0] == "KAN-1"
        await fake_ws.close()


def test_score_includes_comments_signal() -> None:
    """
    Unit test for the scorer: a query that overlaps the comments
    blob beats one that overlaps nothing.
    """
    base = {"id": "x"}
    with_comment = IndexedStory(
        id="x",
        human_id="KAN-1",
        title="Standalone",
        workspace_key="KAN",
        state="backlog",
        description_prefix="",
        comments_blob="deployment pipeline broke when migrating",
        story=base,
    )
    without = IndexedStory(
        id="y",
        human_id="KAN-2",
        title="Standalone",
        workspace_key="KAN",
        state="backlog",
        description_prefix="",
        comments_blob="",
        story=base,
    )
    assert _score("deployment", with_comment) > _score("deployment", without)


async def test_search_enter_opens_story_detail(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    stories = [_story("s-1", "KAN-1", "hello world")]
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_empty_list())
    mock_api.json(
        "GET",
        "/workspaces",
        body={"items": [_workspace()], "next_cursor": None},
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/stories",
        body={"items": stories, "next_cursor": None},
    )
    mock_api.json("GET", "/stories/s-1/comments", body=_empty_list())
    # Story detail routes.
    mock_api.add(
        "GET",
        "/stories/s-1",
        lambda _req: httpx.Response(
            200,
            json=stories[0],
            headers={"ETag": "1"},
        ),
    )
    mock_api.json("GET", "/stories/s-1/comments", body=_empty_list())
    mock_api.json("GET", "/stories/s-1/linkages", body=_empty_list())
    mock_api.add(
        "GET",
        "/audit/entity/story/s-1",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "not yet"}},
        ),
    )

    app = KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, StoryDetailScreen)
        assert app.screen.story["human_id"] == "KAN-1"
        await fake_ws.close()
