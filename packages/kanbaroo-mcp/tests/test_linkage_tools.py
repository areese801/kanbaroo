"""
Tests for linkage-scoped tools.
"""

from __future__ import annotations

from conftest import MockApi, story_body

from kanbaroo_mcp.client import McpApiClient
from kanbaroo_mcp.tools.linkages import build_linkage_tools


def _handler(name: str):  # type: ignore[no-untyped-def]
    for tool in build_linkage_tools():
        if tool.name == name:
            return tool.handler
    raise KeyError(name)


def test_link_stories_resolves_both_ends(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    Both source and target are resolved by human id before the POST.
    """
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-1",
        body=story_body(human_id="KAN-1", story_id="story-1"),
    )
    mock_api.json(
        "GET",
        "/stories/by-key/KAN-2",
        body=story_body(human_id="KAN-2", story_id="story-2"),
    )
    mock_api.json(
        "POST",
        "/linkages",
        status_code=201,
        body={
            "id": "lnk-1",
            "source_type": "story",
            "source_id": "story-1",
            "target_type": "story",
            "target_id": "story-2",
            "link_type": "blocks",
            "created_at": "2026-04-18T00:00:00Z",
            "deleted_at": None,
        },
    )
    _handler("link_stories")(
        client,
        {"source": "KAN-1", "target": "KAN-2", "link_type": "blocks"},
    )
    post = [r for r in mock_api.requests if r.method == "POST"][0]
    assert post.body == {
        "source_type": "story",
        "source_id": "story-1",
        "target_type": "story",
        "target_id": "story-2",
        "link_type": "blocks",
    }


def test_unlink_stories_issues_delete(mock_api: MockApi, client: McpApiClient) -> None:
    """
    ``unlink_stories`` sends a bare DELETE on the linkage id.
    """
    mock_api.json(
        "DELETE",
        "/linkages/lnk-1",
        status_code=204,
    )
    result = _handler("unlink_stories")(client, {"linkage_id": "lnk-1"})
    assert result["linkage_id"] == "lnk-1"
    assert [r.method for r in mock_api.requests] == ["DELETE"]
