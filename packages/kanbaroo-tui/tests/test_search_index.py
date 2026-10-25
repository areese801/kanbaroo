"""
Tests for :mod:`kanbaroo_tui.search_index` driven directly through an
:class:`~kanbaroo_tui.client.AsyncApiClient` on the shared
:class:`MockApi`, with no Textual app involved.

Covers the bulk-comments fast path, the per-story fallback for older
servers (and that the verdict is remembered), pagination, the per-story
comment cap, carry-over of comment text between build phases, build
coalescing, and failure handling.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from kanbaroo_tui.client import ApiRequestError, AsyncApiClient
from kanbaroo_tui.search_index import (
    COMMENTS_PREFIX_LENGTH,
    IndexPhase,
    SearchIndex,
    is_missing_route_404,
    is_search_relevant_event,
)


def _workspace(id_: str = "ws-1", key: str = "KAN") -> dict[str, Any]:
    return {
        "id": id_,
        "key": key,
        "name": key,
        "description": None,
        "next_issue_num": 1,
        "created_at": "2026-04-17T00:00:00Z",
        "updated_at": "2026-04-17T00:00:00Z",
        "deleted_at": None,
        "version": 1,
    }


def _story(id_: str, human_id: str, title: str, workspace_id: str = "ws-1"):
    return {
        "id": id_,
        "workspace_id": workspace_id,
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


def _comment(id_: str, story_id: str, body: str) -> dict[str, Any]:
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


def _page(items: list[dict[str, Any]], next_cursor: str | None = None):
    return {"items": items, "next_cursor": next_cursor}


def _route_404() -> httpx.Response:
    """
    The framework 404 an older server returns for an unknown route.
    """
    return httpx.Response(
        404,
        json={"error": {"code": "not_found", "message": "Not Found", "details": None}},
    )


def _workspace_404(workspace_id: str) -> httpx.Response:
    """
    The service-layer 404 for a missing or soft-deleted workspace.
    """
    return httpx.Response(
        404,
        json={
            "error": {
                "code": "not_found",
                "message": f"workspace {workspace_id} not found",
                "details": {"entity_type": "workspace", "entity_id": workspace_id},
            }
        },
    )


def _client(mock_api) -> AsyncApiClient:
    return AsyncApiClient(
        base_url="http://test.invalid",
        token="kbr_test",
        transport=mock_api.transport(),
    )


def _paths(mock_api, prefix: str) -> list[str]:
    return [r.path for r in mock_api.requests if r.path.startswith(prefix)]


def _seed_stories(mock_api, stories: list[dict[str, Any]]) -> None:
    mock_api.json("GET", "/workspaces", body=_page([_workspace()]))
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_page(stories))


async def test_bulk_endpoint_used_when_available(mock_api) -> None:
    """
    Comment text comes from one ``/workspaces/{id}/comments`` walk,
    grouped by story; no per-story comment requests are made.
    """
    stories = [_story("s-1", "KAN-1", "a"), _story("s-2", "KAN-2", "b")]
    _seed_stories(mock_api, stories)
    mock_api.json(
        "GET",
        "/workspaces/ws-1/comments",
        body=_page(
            [
                _comment("c-1", "s-1", "first on one"),
                _comment("c-2", "s-2", "only on two"),
                _comment("c-3", "s-1", "second on one"),
            ]
        ),
    )
    index = SearchIndex()
    async with _client(mock_api) as client:
        await index.refresh(client)

    assert index.built and index.comments_indexed and not index.stale
    assert index.bulk_comments_supported is True
    assert index.build_count == 1
    assert index.phase == IndexPhase.IDLE
    blobs = {entry.id: entry.comments_blob for entry in index.entries}
    assert blobs == {"s-1": "first on one\nsecond on one", "s-2": "only on two"}
    assert _paths(mock_api, "/stories/") == []
    assert _paths(mock_api, "/workspaces/ws-1/comments") == [
        "/workspaces/ws-1/comments"
    ]


async def test_bulk_endpoint_paginates_and_caps_per_story(mock_api) -> None:
    """
    Every page of the bulk feed is walked and the per-story blob is
    capped at :data:`COMMENTS_PREFIX_LENGTH` characters.
    """
    _seed_stories(mock_api, [_story("s-1", "KAN-1", "a")])
    long_body = "x" * 400
    mock_api.json(
        "GET",
        "/workspaces/ws-1/comments",
        body=_page([_comment("c-1", "s-1", long_body)], next_cursor="page2"),
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-1/comments",
        body=_page([_comment("c-2", "s-1", long_body)]),
    )
    index = SearchIndex()
    async with _client(mock_api) as client:
        await index.refresh(client)

    (entry,) = index.entries
    assert len(entry.comments_blob) == COMMENTS_PREFIX_LENGTH
    bulk_requests = [
        r for r in mock_api.requests if r.path == "/workspaces/ws-1/comments"
    ]
    assert len(bulk_requests) == 2


async def test_missing_route_falls_back_per_story_and_is_remembered(
    mock_api,
) -> None:
    """
    A framework 404 (no workspace entity in the details) means an
    older server: the build falls back to ``/stories/{id}/comments``
    and later builds skip the bulk route entirely.
    """
    stories = [_story("s-1", "KAN-1", "a"), _story("s-2", "KAN-2", "b")]
    _seed_stories(mock_api, stories)
    mock_api.add("GET", "/workspaces/ws-1/comments", lambda _req: _route_404())
    mock_api.json(
        "GET", "/stories/s-1/comments", body={"items": [_comment("c", "s-1", "hit")]}
    )
    mock_api.json("GET", "/stories/s-2/comments", body={"items": []})

    index = SearchIndex()
    async with _client(mock_api) as client:
        await index.refresh(client)
        assert index.bulk_comments_supported is False
        assert index.comments_indexed
        blobs = {entry.id: entry.comments_blob for entry in index.entries}
        assert blobs == {"s-1": "hit", "s-2": ""}
        assert _paths(mock_api, "/workspaces/ws-1/comments") == [
            "/workspaces/ws-1/comments"
        ]
        assert sorted(_paths(mock_api, "/stories/")) == [
            "/stories/s-1/comments",
            "/stories/s-2/comments",
        ]

        index.mark_stale()
        await index.refresh(client)

    assert index.build_count == 2
    # Still exactly one probe of the bulk route for the whole session.
    assert _paths(mock_api, "/workspaces/ws-1/comments") == [
        "/workspaces/ws-1/comments"
    ]
    assert len(_paths(mock_api, "/stories/")) == 4


async def test_workspace_404_skips_without_disabling_bulk(mock_api) -> None:
    """
    A 404 that names the workspace entity means the workspace vanished
    between phases: no fallback, and the bulk route stays trusted.
    """
    _seed_stories(mock_api, [_story("s-1", "KAN-1", "a")])
    mock_api.add(
        "GET", "/workspaces/ws-1/comments", lambda _req: _workspace_404("ws-1")
    )
    index = SearchIndex()
    async with _client(mock_api) as client:
        await index.refresh(client)

    assert index.bulk_comments_supported is None
    assert index.comments_indexed
    assert [entry.comments_blob for entry in index.entries] == [""]
    assert _paths(mock_api, "/stories/") == []


async def test_comment_text_carried_over_between_phases(mock_api) -> None:
    """
    During a refresh, stories keep the comment text from the previous
    build until phase 2 replaces it, so comment hits do not flicker
    away while the comments are refetched.
    """
    _seed_stories(mock_api, [_story("s-1", "KAN-1", "a")])
    gate = asyncio.Event()
    gate.set()
    comments = _page([_comment("c-1", "s-1", "the comment")])

    async def _comments(_request: httpx.Request) -> httpx.Response:
        await gate.wait()
        return httpx.Response(200, json=comments)

    mock_api.add("GET", "/workspaces/ws-1/comments", _comments)

    index = SearchIndex()
    phases: list[tuple[IndexPhase, str]] = []
    comments_phase_reached = asyncio.Event()

    def _record() -> None:
        blob = index.entries[0].comments_blob if index.entries else ""
        phases.append((index.phase, blob))
        if index.phase == IndexPhase.COMMENTS:
            comments_phase_reached.set()

    index.add_listener(_record)
    async with _client(mock_api) as client:
        await index.refresh(client)
        assert index.entries[0].comments_blob == "the comment"

        # Hold the second build's comment fetch so phase 1 is observable.
        gate.clear()
        phases.clear()
        comments_phase_reached.clear()
        task = asyncio.create_task(index.refresh(client))
        await asyncio.wait_for(comments_phase_reached.wait(), timeout=5)
        # Phase 1 of the refresh has landed: fresh story entry, old blob.
        assert (IndexPhase.COMMENTS, "the comment") in phases
        assert not index.comments_indexed
        assert index.entries[0].comments_blob == "the comment"
        gate.set()
        await asyncio.wait_for(task, timeout=5)

    assert index.comments_indexed
    assert phases[-1][0] == IndexPhase.IDLE


async def test_refresh_while_building_runs_exactly_one_follow_up(mock_api) -> None:
    """
    Refresh requests that arrive mid-build coalesce into a single
    follow-up build; builds never overlap.
    """
    gate = asyncio.Event()
    workspaces = _page([_workspace()])

    async def _gated_workspaces(_request: httpx.Request) -> httpx.Response:
        await gate.wait()
        return httpx.Response(200, json=workspaces)

    mock_api.add("GET", "/workspaces", _gated_workspaces)
    mock_api.json("GET", "/workspaces", body=workspaces)
    mock_api.json("GET", "/workspaces/ws-1/stories", body=_page([]))
    mock_api.json("GET", "/workspaces/ws-1/comments", body=_page([]))

    index = SearchIndex()
    async with _client(mock_api) as client:
        first = asyncio.create_task(index.refresh(client))
        await asyncio.sleep(0)
        assert index.building
        await index.refresh(client)
        await index.refresh(client)
        await index.refresh(client)
        assert index.build_count == 0
        gate.set()
        await asyncio.wait_for(first, timeout=5)

    assert not index.building
    assert index.build_count == 2
    assert _paths(mock_api, "/workspaces").count("/workspaces") == 2


async def test_workspace_fetch_failure_leaves_index_stale_and_warns(
    mock_api,
) -> None:
    """
    If the workspace list cannot be fetched the build stops, the index
    stays stale (so the next open retries), and a warning is emitted.
    """
    mock_api.add(
        "GET",
        "/workspaces",
        lambda _req: httpx.Response(
            500,
            json={"error": {"code": "internal_error", "message": "boom"}},
        ),
    )
    index = SearchIndex()
    warnings: list[str] = []
    index.on_warning = warnings.append
    async with _client(mock_api) as client:
        await index.refresh(client)

    assert not index.built
    assert index.stale
    assert index.entries == []
    assert warnings and "search index failed" in warnings[0]


async def test_story_fetch_failure_skips_only_that_workspace(mock_api) -> None:
    """
    One workspace's story list failing does not poison the others.
    """
    mock_api.json(
        "GET",
        "/workspaces",
        body=_page([_workspace("ws-1", "AAA"), _workspace("ws-2", "BBB")]),
    )
    mock_api.add(
        "GET",
        "/workspaces/ws-1/stories",
        lambda _req: httpx.Response(
            500, json={"error": {"code": "internal_error", "message": "boom"}}
        ),
    )
    mock_api.json(
        "GET",
        "/workspaces/ws-2/stories",
        body=_page([_story("s-9", "BBB-1", "ok", "ws-2")]),
    )
    mock_api.json("GET", "/workspaces/ws-2/comments", body=_page([]))
    index = SearchIndex()
    warnings: list[str] = []
    index.on_warning = warnings.append
    async with _client(mock_api) as client:
        await index.refresh(client)

    assert [entry.human_id for entry in index.entries] == ["BBB-1"]
    assert index.entries[0].workspace_key == "BBB"
    assert any("skipped AAA" in w for w in warnings)
    assert _paths(mock_api, "/workspaces/ws-1/comments") == []


def test_is_missing_route_404_rules() -> None:
    """
    Only a 404 whose details do not name a workspace entity counts as
    "route not on this server".
    """

    def _exc(status: int, details: dict[str, Any] | None) -> ApiRequestError:
        return ApiRequestError(
            status_code=status, code="not_found", message="x", details=details
        )

    assert is_missing_route_404(_exc(404, None))
    assert is_missing_route_404(_exc(404, {}))
    assert is_missing_route_404(_exc(404, {"entity_type": "story"}))
    assert not is_missing_route_404(_exc(404, {"entity_type": "workspace"}))
    assert not is_missing_route_404(_exc(500, None))
    assert not is_missing_route_404(_exc(401, None))


def test_is_search_relevant_event() -> None:
    assert is_search_relevant_event({"event_type": "story.created"})
    assert is_search_relevant_event({"event_type": "story.commented"})
    assert is_search_relevant_event({"event_type": "comment.deleted"})
    assert not is_search_relevant_event({"event_type": "epic.updated"})
    assert not is_search_relevant_event({"event_type": "workspace.created"})
    assert not is_search_relevant_event({})
