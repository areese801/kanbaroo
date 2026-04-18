"""
Tests for the story-scoped tools.

Covers human-id resolution, the 412-retry helper, the split between
``update_story`` and ``transition_story_state``, and error translation
when the server rejects an invalid state transition.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from conftest import MockApi, epic_body, story_body, ws_body

from kanberoo_mcp.client import McpApiClient, McpApiRequestError
from kanberoo_mcp.tools.stories import build_story_tools


def _handler(name: str):  # type: ignore[no-untyped-def]
    """
    Look up a story-tool handler by name.
    """
    for tool in build_story_tools():
        if tool.name == name:
            return tool.handler
    raise KeyError(name)


def test_get_story_uses_by_key_resolver(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    Passing 'KAN-1' triggers ``GET /stories/by-key/KAN-1`` and the
    handler folds comments and linkages into the body.
    """
    mock_api.json("GET", "/stories/by-key/KAN-1", body=story_body())
    mock_api.json(
        "GET",
        "/stories/story-1/comments",
        body={"items": [{"id": "c1"}]},
    )
    mock_api.json(
        "GET",
        "/stories/story-1/linkages",
        body={"items": []},
    )
    result = _handler("get_story")(client, {"story": "KAN-1"})
    assert result["id"] == "story-1"
    assert result["comments"] == [{"id": "c1"}]
    assert result["linkages"] == []


def test_get_story_uses_uuid_resolver(mock_api: MockApi, client: McpApiClient) -> None:
    """
    Passing a UUID-shaped string goes through ``GET /stories/{id}``.
    """
    mock_api.json(
        "GET",
        "/stories/abc123uuid",
        body=story_body(story_id="abc123uuid"),
    )
    mock_api.json(
        "GET",
        "/stories/abc123uuid/comments",
        body={"items": []},
    )
    mock_api.json(
        "GET",
        "/stories/abc123uuid/linkages",
        body={"items": []},
    )
    _handler("get_story")(client, {"story": "abc123uuid"})
    paths = [r.path for r in mock_api.requests]
    assert "/stories/abc123uuid" in paths
    assert "/stories/by-key/abc123uuid" not in paths


def test_list_stories_resolves_workspace_and_epic(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    Workspace key resolves to a UUID and epic human id resolves to a
    UUID before either hits the filter query string.
    """
    mock_api.json("GET", "/workspaces/KAN", body=ws_body("KAN"))
    mock_api.json("GET", "/epics/by-key/KAN-4", body=epic_body())
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/stories",
        body={"items": [story_body()], "next_cursor": None},
    )
    _handler("list_stories")(
        client,
        {
            "workspace": "KAN",
            "state": "in_progress",
            "priority": "high",
            "epic": "KAN-4",
            "tag": "bug",
            "limit": 50,
        },
    )
    list_req = [r for r in mock_api.requests if r.path == "/workspaces/ws-kan/stories"][
        0
    ]
    assert list_req.params == {
        "state": "in_progress",
        "priority": "high",
        "tag": "bug",
        "limit": "50",
        "epic_id": "epic-1",
    }


def test_create_story_resolves_epic_human_id(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    A human-id epic reference resolves to a UUID before the POST.
    """
    mock_api.json("GET", "/workspaces/KAN", body=ws_body("KAN"))
    mock_api.json("GET", "/epics/by-key/KAN-4", body=epic_body())
    mock_api.json(
        "POST",
        "/workspaces/ws-kan/stories",
        status_code=201,
        body=story_body(human_id="KAN-7", story_id="story-7"),
    )
    result = _handler("create_story")(
        client,
        {
            "workspace": "KAN",
            "title": "New thing",
            "priority": "high",
            "epic": "KAN-4",
        },
    )
    assert result["story"]["human_id"] == "KAN-7"
    post = [r for r in mock_api.requests if r.method == "POST"][0]
    assert post.body == {
        "title": "New thing",
        "priority": "high",
        "epic_id": "epic-1",
    }


def test_update_story_sends_if_match_header(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    ``update_story`` always sends ``If-Match`` with the story's current
    version on the PATCH.
    """
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=story_body(version=3),
    )
    mock_api.json(
        "GET",
        "/stories/story-1",
        body=story_body(version=3),
        headers={"etag": "3"},
    )
    mock_api.json(
        "PATCH",
        "/stories/story-1",
        body=story_body(version=4, description="new"),
    )
    _handler("update_story")(
        client,
        {"story": "KAN-1", "description": "new"},
    )
    patch = [r for r in mock_api.requests if r.method == "PATCH"][0]
    assert patch.headers.get("if-match") == "3"
    assert patch.body == {"description": "new"}


def test_update_story_retries_once_on_412(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    First PATCH returns 412; the handler refetches the ETag and
    retries; second PATCH succeeds.
    """
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=story_body(version=3),
    )
    # First ETag fetch + first PATCH (rejected) + refetch + retry PATCH.
    mock_api.add(
        "GET",
        "/stories/story-1",
        lambda _r: httpx.Response(
            200,
            json=story_body(version=3),
            headers={"etag": "3"},
        ),
    )
    mock_api.add(
        "PATCH",
        "/stories/story-1",
        lambda _r: httpx.Response(
            412,
            json={
                "error": {
                    "code": "precondition_failed",
                    "message": "version mismatch",
                }
            },
        ),
    )
    mock_api.add(
        "GET",
        "/stories/story-1",
        lambda _r: httpx.Response(
            200,
            json=story_body(version=4),
            headers={"etag": "4"},
        ),
    )
    mock_api.add(
        "PATCH",
        "/stories/story-1",
        lambda _r: httpx.Response(
            200,
            json=story_body(version=5, description="new"),
        ),
    )
    result = _handler("update_story")(
        client,
        {"story": "KAN-1", "description": "new"},
    )
    assert result["story"]["version"] == 5
    patches = [r for r in mock_api.requests if r.method == "PATCH"]
    assert len(patches) == 2
    assert patches[0].headers.get("if-match") == "3"
    assert patches[1].headers.get("if-match") == "4"


def test_update_story_surfaces_second_412_cleanly(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    Two consecutive 412s raise a :class:`McpApiRequestError` with a
    helpful message rather than looping forever.
    """
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=story_body(version=3),
    )
    for _ in range(2):
        mock_api.add(
            "GET",
            "/stories/story-1",
            lambda _r: httpx.Response(
                200,
                json=story_body(version=3),
                headers={"etag": "3"},
            ),
        )
        mock_api.add(
            "PATCH",
            "/stories/story-1",
            lambda _r: httpx.Response(
                412,
                json={
                    "error": {
                        "code": "precondition_failed",
                        "message": "version mismatch",
                    }
                },
            ),
        )
    with pytest.raises(McpApiRequestError) as excinfo:
        _handler("update_story")(
            client,
            {"story": "KAN-1", "description": "new"},
        )
    assert excinfo.value.status_code == 412
    assert "changed twice" in excinfo.value.message


def test_transition_story_state_sends_payload_and_etag(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    Valid transition POSTs to the transition endpoint with If-Match.
    """
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=story_body(version=3),
    )
    mock_api.json(
        "GET",
        "/stories/story-1",
        body=story_body(version=3),
        headers={"etag": "3"},
    )
    mock_api.json(
        "POST",
        "/stories/story-1/transition",
        body=story_body(version=4, state="in_progress"),
    )
    result = _handler("transition_story_state")(
        client,
        {"story": "KAN-1", "to_state": "in_progress", "reason": "picked it up"},
    )
    assert result["story"]["state"] == "in_progress"
    post = [r for r in mock_api.requests if r.method == "POST"][0]
    assert post.body == {"to_state": "in_progress", "reason": "picked it up"}
    assert post.headers.get("if-match") == "3"


def test_transition_story_state_surfaces_invalid_transition(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    The server rejects ``backlog -> done`` with a 400
    ``validation_error``; that surfaces as a typed
    :class:`McpApiRequestError` that callers can render.
    """
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=story_body(version=3, state="backlog"),
    )
    mock_api.json(
        "GET",
        "/stories/story-1",
        body=story_body(version=3, state="backlog"),
        headers={"etag": "3"},
    )
    mock_api.error(
        "POST",
        "/stories/story-1/transition",
        status_code=400,
        code="validation_error",
        message="invalid transition: backlog -> done",
    )
    with pytest.raises(McpApiRequestError) as excinfo:
        _handler("transition_story_state")(
            client,
            {"story": "KAN-1", "to_state": "done"},
        )
    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "validation_error"


def test_update_story_noop_skips_patch(mock_api: MockApi, client: McpApiClient) -> None:
    """
    ``update_story`` with only the story reference short-circuits -
    we never GET the ETag or PATCH anything.
    """
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=story_body(version=3),
    )
    result = _handler("update_story")(client, {"story": "KAN-1"})
    assert result["message"] == "no fields to update"
    assert [r.method for r in mock_api.requests] == ["GET"]


def _last_post_body(mock_api: MockApi) -> Any:
    """
    Helper used by tests that need the most-recent POST body.
    """
    return [r for r in mock_api.requests if r.method == "POST"][-1].body
