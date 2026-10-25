"""
Tests for the global fuzzy-search overlay.

Covers the screen's behavior on top of the app-owned index: ranking,
``enter`` opening the right story, instant reopen with no HTTP
traffic, non-blocking build with the input focused immediately, hint
text per build phase, and the debounced WebSocket-driven rebuild.
Pure index mechanics (bulk endpoint, 404 fallback, coalescing) live in
``test_search_index.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from kanbaroo_tui.app import KanbarooTuiApp
from kanbaroo_tui.screens.search import (
    IndexedStory,
    SearchScreen,
    _score,
    rank_entries,
)
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


def _comment(id_, story_id, body):
    return {
        "id": id_,
        "story_id": story_id,
        "parent_id": None,
        "body": body,
        "actor_type": "human",
        "actor_id": "adam",
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": "2026-04-17T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def _register_routes(mock_api, stories, comments=None) -> None:
    """
    Register every route the workspace list and the search index hit.
    Each is registered once so it answers every call.
    """
    mock_api.json(
        "GET", "/workspaces", body={"items": [_workspace()], "next_cursor": None}
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET", "/workspaces/ws-1/stories", body={"items": stories, "next_cursor": None}
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/comments",
        body={"items": comments or [], "next_cursor": None},
    )


def _app(tui_config, client_factory, ws_factory, **kwargs) -> KanbarooTuiApp:
    return KanbarooTuiApp(
        config=tui_config,
        client_factory=client_factory,
        ws_factory=ws_factory,
        **kwargs,
    )


async def _open_search_and_wait(pilot) -> SearchScreen:
    """
    Press ``/`` and wait for the background index build to finish.
    """
    await pilot.press("slash")
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()
    search = pilot.app.screen
    assert isinstance(search, SearchScreen)
    return search


def _ws_event(event_type: str, story_id: str = "s-1") -> dict[str, Any]:
    return {
        "event_id": f"e-{event_type}",
        "event_type": event_type,
        "occurred_at": "2026-04-17T00:00:00Z",
        "actor_type": "human",
        "actor_id": "adam",
        "entity_type": "story",
        "entity_id": story_id,
        "entity_version": 2,
        "payload": {"workspace_id": "ws-1", "story_id": story_id},
    }


async def test_search_narrows_results_by_query(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    stories = [
        _story("s-1", "KAN-1", "authentication token rotation"),
        _story("s-2", "KAN-2", "fix markdown rendering bug"),
        _story("s-3", "KAN-3", "audit feed refresh"),
    ]
    _register_routes(mock_api, stories)
    app = _app(tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, WorkspaceListScreen)
        search = await _open_search_and_wait(pilot)
        assert len(search.index) == 3
        # Empty query shows every entry.
        assert len(search.ranked) == 3

        await pilot.press("a", "u", "d", "i", "t")
        search.flush_pending_rerank()
        human_ids = [entry.human_id for entry in search.ranked]
        # "audit feed refresh" should rank first.
        assert human_ids[0] == "KAN-3"
        await fake_ws.close()


async def test_search_rerank_timer_fires_without_manual_flush(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    The debounced re-rank lands on its own shortly after the last
    keystroke; a test does not have to flush by hand.
    """
    stories = [
        _story("s-1", "KAN-1", "authentication token rotation"),
        _story("s-3", "KAN-3", "audit feed refresh"),
    ]
    _register_routes(mock_api, stories)
    app = _app(tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        search = await _open_search_and_wait(pilot)
        await pilot.press("a", "u", "d", "i", "t")
        await pilot.pause(0.4)
        assert [entry.human_id for entry in search.ranked][0] == "KAN-3"
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
    _register_routes(
        mock_api,
        stories,
        comments=[_comment("c-1", "s-1", "deployment pipeline broke when migrating")],
    )
    app = _app(tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        search = await _open_search_and_wait(pilot)
        assert app.search_index.comments_indexed
        await pilot.press(*list("deployment"))
        search.flush_pending_rerank()
        human_ids = [entry.human_id for entry in search.ranked]
        assert human_ids[0] == "KAN-1"
        await fake_ws.close()


def _entry(human_id: str, title: str, comments: str = "") -> IndexedStory:
    return IndexedStory(
        id=human_id,
        human_id=human_id,
        title=title,
        workspace_key="KAN",
        state="backlog",
        description_prefix="",
        comments_blob=comments,
        story={"id": human_id},
    )


def test_score_includes_comments_signal() -> None:
    """
    Unit test for the scorer: a query that appears in the comments
    blob beats one that overlaps nothing.
    """
    with_comment = _entry(
        "KAN-1", "Standalone", "deployment pipeline broke when migrating"
    )
    without = _entry("KAN-2", "Standalone")
    assert _score("deployment", with_comment) > _score("deployment", without)


def test_score_human_id_exact_match_wins() -> None:
    """
    Typing a human id ranks that story above its neighbors, including
    one whose id merely starts with the query.
    """
    target = _entry("KAN-12", "unrelated words")
    prefix_sibling = _entry("KAN-120", "unrelated words")
    other = _entry("KAN-1", "unrelated words")
    assert _score("KAN-12", target) > _score("KAN-12", prefix_sibling)
    assert _score("KAN-12", target) > _score("KAN-12", other)
    assert _score("kan-12", target) == _score("KAN-12", target)


def _entry_full(
    human_id: str, title: str, description: str = "", comments: str = ""
) -> IndexedStory:
    return IndexedStory(
        id=human_id,
        human_id=human_id,
        title=title,
        workspace_key="KAN",
        state="backlog",
        description_prefix=description,
        comments_blob=comments,
        story={"id": human_id},
    )


def test_exact_id_beats_story_quoting_that_id() -> None:
    """
    A story whose description and comments contain the queried id (so
    it collects the substring weights and hits the 1.0 cap) still ranks
    below the story that *is* that id.
    """
    exact = _entry_full("KAN-2", "something unrelated")
    quoting = _entry_full(
        "KAN-24",
        "follow-up to KAN-2",
        description="split out of KAN-2 after review",
        comments="see KAN-2 for the original discussion",
    )
    ranked = rank_entries("KAN-2", [quoting, exact])
    assert [entry.human_id for entry in ranked][:2] == ["KAN-2", "KAN-24"]
    # Case and surrounding whitespace do not matter.
    ranked = rank_entries("  kan-2 ", [quoting, exact])
    assert ranked[0].human_id == "KAN-2"


def test_exact_id_beats_longer_sibling_id() -> None:
    """
    ``KAN-7`` outranks ``KAN-71`` and ``KAN-2`` outranks ``KAN-24``
    even though the longer ids earn the same prefix bonuses.
    """
    entries = [
        _entry_full("KAN-71", "seventy one"),
        _entry_full("KAN-7", "seven"),
        _entry_full("KAN-24", "twenty four"),
        _entry_full("KAN-2", "two"),
        _entry_full("KAN-20", "twenty"),
    ]
    assert rank_entries("KAN-7", entries)[0].human_id == "KAN-7"
    assert rank_entries("KAN-2", entries)[0].human_id == "KAN-2"
    assert rank_entries("kan-2", entries)[0].human_id == "KAN-2"


def test_prefix_query_without_exact_id_ranks_by_score() -> None:
    """
    A query that is only a prefix of several ids (no exact match) keeps
    the plain score ordering: the entry with the extra title hit wins.
    """
    plain = _entry_full("KAN-71", "seventy one")
    boosted = _entry_full("KAN-72", "KAN-7 cleanup")
    ranked = rank_entries("KAN-7", [plain, boosted])
    assert [entry.human_id for entry in ranked] == ["KAN-72", "KAN-71"]
    assert _score("KAN-7", boosted) > _score("KAN-7", plain)


def test_score_uses_precomputed_lowercase_fields() -> None:
    """
    Comment text set after construction is folded too, so phase 2
    updates participate in matching.
    """
    entry = _entry("KAN-1", "Title")
    before = _score("rollback", entry)
    entry.set_comments("Needs ROLLBACK plan")
    assert entry.comments_lower == "needs rollback plan"
    assert _score("rollback", entry) > before


async def test_search_enter_opens_story_detail(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    ``enter`` right after typing opens the story matching the typed
    query even though the re-rank timer has not fired yet.
    """
    stories = [
        _story("s-1", "KAN-1", "hello world"),
        _story("s-2", "KAN-2", "zebra crossing"),
    ]
    _register_routes(mock_api, stories)
    # Story detail routes.
    mock_api.add(
        "GET",
        "/stories/s-2",
        lambda _req: httpx.Response(200, json=stories[1], headers={"ETag": "1"}),
    )
    mock_api.json("GET", "/stories/s-2/comments", body=_empty_list())
    mock_api.json("GET", "/stories/s-2/linkages", body=_empty_list())
    mock_api.add(
        "GET",
        "/audit/entity/story/s-2",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "not yet"}},
        ),
    )
    app = _app(tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _open_search_and_wait(pilot)
        await pilot.press(*list("zebra"), "enter")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, StoryDetailScreen)
        assert app.screen.story["human_id"] == "KAN-2"
        await fake_ws.close()


async def test_search_index_reused_across_opens(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    The second open renders from the cached index and makes no HTTP
    requests at all.
    """
    stories = [_story("s-1", "KAN-1", "hello world")]
    _register_routes(mock_api, stories)
    app = _app(tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        first = await _open_search_and_wait(pilot)
        assert len(first.ranked) == 1
        assert app.search_index.build_count == 1
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, WorkspaceListScreen)

        requests_before = len(mock_api.requests)
        await pilot.press("slash")
        await pilot.pause()
        second = app.screen
        assert isinstance(second, SearchScreen)
        assert second is not first
        assert [entry.human_id for entry in second.ranked] == ["KAN-1"]
        assert second.hint_text == "1 result (index: 1 stories)"
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(mock_api.requests) == requests_before
        assert app.search_index.build_count == 1
        await fake_ws.close()


async def test_search_input_focused_before_build_completes(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    The input is focused and the hint reads "indexing stories..." while
    the first fetch is still in flight; results land once it returns.
    """
    gate = asyncio.Event()
    workspaces = {"items": [_workspace()], "next_cursor": None}

    async def _gated_workspaces(_request: httpx.Request) -> httpx.Response:
        await gate.wait()
        return httpx.Response(200, json=workspaces)

    # The workspace list screen fetches /workspaces first; let that one
    # through immediately and gate the search index's fetch.
    mock_api.json("GET", "/workspaces", body=workspaces)
    mock_api.add("GET", "/workspaces", _gated_workspaces)
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    stories = [_story("s-1", "KAN-1", "hello world")]
    mock_api.json(
        "GET", "/workspaces/ws-1/stories", body={"items": stories, "next_cursor": None}
    )
    mock_api.json("GET", "/workspaces/ws-1/comments", body=_empty_list())

    app = _app(tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        search = app.screen
        assert isinstance(search, SearchScreen)
        assert search.query_one("#search-input").has_focus
        assert not app.search_index.built
        assert app.search_index.building
        assert search.hint_text == "0 results (indexing stories...)"
        assert search.ranked == []

        gate.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.search_index.built
        assert [entry.human_id for entry in search.ranked] == ["KAN-1"]
        assert search.hint_text == "1 result (index: 1 stories)"
        await fake_ws.close()


async def test_search_hint_reflects_comment_phase_and_reranks_when_done(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    After phase 1 the table already shows stories and the hint says
    comments are being indexed; when phase 2 lands the current query
    is re-ranked so comment-only hits surface without retyping.
    """
    gate = asyncio.Event()
    comments = {
        "items": [_comment("c-1", "s-2", "deployment pipeline broke")],
        "next_cursor": None,
    }

    async def _gated_comments(_request: httpx.Request) -> httpx.Response:
        await gate.wait()
        return httpx.Response(200, json=comments)

    stories = [
        _story("s-1", "KAN-1", "Standalone title"),
        _story("s-2", "KAN-2", "Another story"),
    ]
    mock_api.json(
        "GET", "/workspaces", body={"items": [_workspace()], "next_cursor": None}
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.json(
        "GET", "/workspaces/ws-1/stories", body={"items": stories, "next_cursor": None}
    )
    mock_api.add("GET", "/workspaces/ws-1/comments", _gated_comments)

    app = _app(tui_config, client_factory, ws_factory)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        await pilot.pause()
        search = app.screen
        assert isinstance(search, SearchScreen)
        assert app.search_index.built
        assert not app.search_index.comments_indexed
        assert len(search.ranked) == 2
        assert search.hint_text == "2 results (index: 2 stories, indexing comments...)"

        await pilot.press(*list("deployment"))
        search.flush_pending_rerank()
        gate.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.search_index.comments_indexed
        assert search.hint_text.endswith("(index: 2 stories)")
        assert [entry.human_id for entry in search.ranked][0] == "KAN-2"
        await fake_ws.close()


async def test_ws_event_burst_marks_stale_and_rebuilds_once(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    A burst of ``story.*`` / ``comment.*`` events marks the index stale
    and results in exactly one background rebuild after the debounce.
    """
    stories = [_story("s-1", "KAN-1", "hello world")]
    _register_routes(mock_api, stories)
    app = _app(tui_config, client_factory, ws_factory, search_rebuild_debounce=0.05)
    async with app.run_test() as pilot:
        await pilot.pause()
        search = await _open_search_and_wait(pilot)
        assert app.search_index.build_count == 1
        assert not app.search_index.stale

        for event_type in (
            "story.created",
            "story.updated",
            "story.commented",
            "comment.updated",
            "story.transitioned",
        ):
            await fake_ws.push(_ws_event(event_type))
        await pilot.pause()
        assert app.search_index.stale

        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.search_index.build_count == 2
        assert not app.search_index.stale
        assert isinstance(app.screen, SearchScreen)
        assert len(search.ranked) == 1
        await fake_ws.close()


async def test_ws_event_before_first_open_does_not_fetch(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Events arriving before the user ever opens search mark the index
    stale but do not trigger a build; nobody is looking.
    """
    _register_routes(mock_api, [_story("s-1", "KAN-1", "hello world")])
    app = _app(tui_config, client_factory, ws_factory, search_rebuild_debounce=0.05)
    async with app.run_test() as pilot:
        await pilot.pause()
        await fake_ws.push(_ws_event("story.created"))
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        assert app.search_index.stale
        assert not app.search_index.built
        assert app.search_index.build_count == 0
        await fake_ws.close()


async def test_unrelated_ws_event_does_not_mark_stale(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    _register_routes(mock_api, [_story("s-1", "KAN-1", "hello world")])
    app = _app(tui_config, client_factory, ws_factory, search_rebuild_debounce=0.05)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _open_search_and_wait(pilot)
        await fake_ws.push(_ws_event("epic.updated"))
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        assert not app.search_index.stale
        assert app.search_index.build_count == 1
        await fake_ws.close()


async def test_stale_index_renders_cached_results_then_refreshes(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    Opening search with a stale index shows the cached rows at once and
    refreshes in the background; the refreshed data replaces them.
    """
    current = [_story("s-1", "KAN-1", "hello world")]
    gate = asyncio.Event()
    gate.set()

    async def _stories(_request: httpx.Request) -> httpx.Response:
        await gate.wait()
        return httpx.Response(200, json={"items": list(current), "next_cursor": None})

    mock_api.json(
        "GET", "/workspaces", body={"items": [_workspace()], "next_cursor": None}
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.add("GET", "/workspaces/ws-1/stories", _stories)
    mock_api.json("GET", "/workspaces/ws-1/comments", body=_empty_list())
    # A very long debounce so the event alone never triggers a rebuild;
    # the reopen has to.
    app = _app(tui_config, client_factory, ws_factory, search_rebuild_debounce=600)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _open_search_and_wait(pilot)
        await pilot.press("escape")
        await pilot.pause()

        await fake_ws.push(_ws_event("story.created", story_id="s-2"))
        await pilot.pause()
        assert app.search_index.stale
        current.append(_story("s-2", "KAN-2", "brand new"))
        # Hold the refresh's story fetch so the cached render is observable.
        gate.clear()

        await pilot.press("slash")
        await pilot.pause()
        search = app.screen
        assert isinstance(search, SearchScreen)
        # Cached rows render before the refresh lands.
        assert [entry.human_id for entry in search.ranked] == ["KAN-1"]
        assert app.search_index.building
        assert search.hint_text == "1 result (index: 1 stories, refreshing...)"
        gate.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.search_index.build_count == 2
        assert [entry.human_id for entry in search.ranked] == ["KAN-1", "KAN-2"]
        await fake_ws.close()


async def test_index_update_preserves_cursor_row(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    A background refresh re-renders the table without yanking the
    cursor back to the top: the highlighted story stays highlighted and
    ``enter`` opens it, not the first row.
    """
    stories = [
        _story("s-1", "KAN-1", "alpha"),
        _story("s-2", "KAN-2", "bravo"),
        _story("s-3", "KAN-3", "charlie"),
        _story("s-4", "KAN-4", "delta"),
    ]
    _register_routes(mock_api, stories)
    mock_api.add(
        "GET",
        "/stories/s-3",
        lambda _req: httpx.Response(200, json=stories[2], headers={"ETag": "1"}),
    )
    mock_api.json("GET", "/stories/s-3/comments", body=_empty_list())
    mock_api.json("GET", "/stories/s-3/linkages", body=_empty_list())
    mock_api.add(
        "GET",
        "/audit/entity/story/s-3",
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "not yet"}},
        ),
    )
    app = _app(tui_config, client_factory, ws_factory, search_rebuild_debounce=0.05)
    async with app.run_test() as pilot:
        await pilot.pause()
        search = await _open_search_and_wait(pilot)
        assert len(search.ranked) == 4
        await pilot.press("down", "down")
        await pilot.pause()
        table = search.query_one("#search-table")
        assert table.cursor_row == 2

        # A WS event drives a full background refresh, which notifies
        # the screen several times; the cursor must survive all of them.
        await fake_ws.push(_ws_event("story.updated", story_id="s-1"))
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.search_index.build_count == 2
        assert table.cursor_row == 2
        assert search.ranked[table.cursor_row].human_id == "KAN-3"

        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, StoryDetailScreen)
        assert app.screen.story["human_id"] == "KAN-3"
        await fake_ws.close()


async def test_index_update_with_vanished_row_falls_back_to_top(
    mock_api, fake_ws, tui_config, client_factory, ws_factory
):
    """
    If the highlighted story is gone after a refresh the cursor rests
    at row 0 rather than pointing at a stale key.
    """
    current = [
        _story("s-1", "KAN-1", "alpha"),
        _story("s-2", "KAN-2", "bravo"),
        _story("s-3", "KAN-3", "charlie"),
    ]
    mock_api.json(
        "GET", "/workspaces", body={"items": [_workspace()], "next_cursor": None}
    )
    mock_api.json("GET", "/workspaces/ws-1/epics", body=_empty_list())
    mock_api.add(
        "GET",
        "/workspaces/ws-1/stories",
        lambda _req: httpx.Response(
            200, json={"items": list(current), "next_cursor": None}
        ),
    )
    mock_api.json("GET", "/workspaces/ws-1/comments", body=_empty_list())
    app = _app(tui_config, client_factory, ws_factory, search_rebuild_debounce=0.05)
    async with app.run_test() as pilot:
        await pilot.pause()
        search = await _open_search_and_wait(pilot)
        await pilot.press("down", "down")
        await pilot.pause()
        table = search.query_one("#search-table")
        assert table.cursor_row == 2

        current.pop()  # KAN-3 disappears server-side
        await fake_ws.push(_ws_event("story.deleted", story_id="s-3"))
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert [entry.human_id for entry in search.ranked] == ["KAN-1", "KAN-2"]
        assert table.cursor_row == 0
        await fake_ws.close()
