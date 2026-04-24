"""
Tests for tag-scoped tools.

Both add_tag_to_story and remove_tag_from_story do a by-name
resolution in the story's workspace before touching the association
endpoint; these tests pin that behaviour.
"""

from __future__ import annotations

from conftest import MockApi, story_body, tag_body, ws_body

from kanbaroo_mcp.client import McpApiClient
from kanbaroo_mcp.tools.tags import build_tag_tools


def _handler(name: str):  # type: ignore[no-untyped-def]
    for tool in build_tag_tools():
        if tool.name == name:
            return tool.handler
    raise KeyError(name)


def test_list_tags_resolves_workspace(mock_api: MockApi, client: McpApiClient) -> None:
    """
    The workspace key is resolved to a UUID before listing tags.
    """
    mock_api.json("GET", "/workspaces/by-key/KAN", body=ws_body("KAN"))
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/tags",
        body={"items": [tag_body(name="bug")]},
    )
    result = _handler("list_tags")(client, {"workspace": "KAN"})
    assert result["items"][0]["name"] == "bug"


def test_add_tag_to_story_resolves_tag_by_name(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    ``add_tag_to_story`` calls /workspaces/{id}/tags to find the tag
    UUID before POSTing the association.
    """
    mock_api.json("GET", "/stories/by-key/KAN-1", body=story_body())
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/tags",
        body={"items": [tag_body(tag_id="tag-bug", name="bug")]},
    )
    mock_api.json(
        "POST",
        "/stories/story-1/tags",
        body=story_body(),
    )
    _handler("add_tag_to_story")(
        client,
        {"story": "KAN-1", "tag_name": "bug"},
    )
    post = [r for r in mock_api.requests if r.method == "POST"][0]
    assert post.body == {"tag_ids": ["tag-bug"]}


def test_add_tag_to_story_surfaces_missing_tag(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    If the named tag doesn't exist we let ``not_found`` propagate so
    the agent knows to ask the user before creating one.
    """
    from kanbaroo_mcp.client import McpApiRequestError

    mock_api.json("GET", "/stories/by-key/KAN-1", body=story_body())
    mock_api.json("GET", "/workspaces/ws-kan/tags", body={"items": []})
    import pytest

    with pytest.raises(McpApiRequestError) as excinfo:
        _handler("add_tag_to_story")(
            client,
            {"story": "KAN-1", "tag_name": "nosuch"},
        )
    assert excinfo.value.code == "not_found"


def test_remove_tag_from_story_resolves_and_deletes(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    Remove-by-name resolves then DELETEs the association.
    """
    mock_api.json("GET", "/stories/by-key/KAN-1", body=story_body())
    mock_api.json(
        "GET",
        "/workspaces/ws-kan/tags",
        body={"items": [tag_body(tag_id="tag-bug", name="bug")]},
    )
    mock_api.json(
        "DELETE",
        "/stories/story-1/tags/tag-bug",
        status_code=204,
    )
    result = _handler("remove_tag_from_story")(
        client,
        {"story": "KAN-1", "tag_name": "bug"},
    )
    assert "removed" in result["message"]


def test_remove_tag_from_story_unknown_tag_is_noop(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    Removing an unknown-by-name tag is a silent no-op; no DELETE is
    issued.
    """
    mock_api.json("GET", "/stories/by-key/KAN-1", body=story_body())
    mock_api.json("GET", "/workspaces/ws-kan/tags", body={"items": []})
    result = _handler("remove_tag_from_story")(
        client,
        {"story": "KAN-1", "tag_name": "nosuch"},
    )
    assert "does not exist" in result["message"]
    assert all(r.method == "GET" for r in mock_api.requests)
