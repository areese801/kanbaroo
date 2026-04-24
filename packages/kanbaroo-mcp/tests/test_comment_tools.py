"""
Tests for comment-scoped tools.
"""

from __future__ import annotations

from conftest import MockApi, story_body

from kanbaroo_mcp.client import McpApiClient
from kanbaroo_mcp.tools.comments import build_comment_tools


def _handler(name: str):  # type: ignore[no-untyped-def]
    for tool in build_comment_tools():
        if tool.name == name:
            return tool.handler
    raise KeyError(name)


def test_comment_on_story_posts_body(mock_api: MockApi, client: McpApiClient) -> None:
    """
    A top-level comment POSTs ``{body}`` with no parent_id.
    """
    mock_api.json("GET", "/stories/by-key/KAN-1", body=story_body())
    mock_api.json(
        "POST",
        "/stories/story-1/comments",
        status_code=201,
        body={
            "id": "c1",
            "story_id": "story-1",
            "parent_id": None,
            "body": "looks good",
            "actor_type": "claude",
            "actor_id": "outer-claude",
            "created_at": "2026-04-18T00:00:00Z",
            "updated_at": "2026-04-18T00:00:00Z",
            "deleted_at": None,
            "version": 1,
        },
    )
    result = _handler("comment_on_story")(
        client,
        {"story": "KAN-1", "body": "looks good"},
    )
    assert result["comment"]["body"] == "looks good"
    post = [r for r in mock_api.requests if r.method == "POST"][0]
    assert post.body == {"body": "looks good"}


def test_comment_on_story_with_parent_comment(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    Passing ``parent_comment_id`` maps to the REST payload's
    ``parent_id`` field.
    """
    mock_api.json("GET", "/stories/by-key/KAN-1", body=story_body())
    mock_api.json(
        "POST",
        "/stories/story-1/comments",
        status_code=201,
        body={
            "id": "c2",
            "story_id": "story-1",
            "parent_id": "c1",
            "body": "agreed",
            "actor_type": "claude",
            "actor_id": "outer-claude",
            "created_at": "2026-04-18T00:00:00Z",
            "updated_at": "2026-04-18T00:00:00Z",
            "deleted_at": None,
            "version": 1,
        },
    )
    _handler("comment_on_story")(
        client,
        {"story": "KAN-1", "body": "agreed", "parent_comment_id": "c1"},
    )
    post = [r for r in mock_api.requests if r.method == "POST"][0]
    assert post.body == {"body": "agreed", "parent_id": "c1"}
