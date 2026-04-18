"""
Tests for the audit tool.

The REST audit router is not wired into the API yet (see the
REST-side gaps note in the PR body); these tests exercise only the
client-side shaping done by the tool handler - entity parsing and
reference resolution - without asserting that the audit endpoint
itself exists. They mock the response shape we expect once it lands.
"""

from __future__ import annotations

import pytest
from conftest import MockApi, epic_body, story_body, ws_body

from kanberoo_mcp.client import McpApiClient, McpApiRequestError
from kanberoo_mcp.tools.audit import build_audit_tools


def _handler(name: str):  # type: ignore[no-untyped-def]
    for tool in build_audit_tools():
        if tool.name == name:
            return tool.handler
    raise KeyError(name)


def test_get_audit_trail_story_reference(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    ``story/KAN-1`` resolves to the story UUID before hitting the
    audit endpoint.
    """
    mock_api.json("GET", "/stories/by-key/KAN-1", body=story_body())
    mock_api.json(
        "GET",
        "/audit/entity/story/story-1",
        body={"items": []},
    )
    result = _handler("get_audit_trail")(client, {"entity": "story/KAN-1"})
    assert result == {"items": []}


def test_get_audit_trail_epic_reference(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    ``epic/KAN-4`` resolves to the epic UUID.
    """
    mock_api.json("GET", "/epics/by-key/KAN-4", body=epic_body())
    mock_api.json(
        "GET",
        "/audit/entity/epic/epic-1",
        body={"items": []},
    )
    _handler("get_audit_trail")(client, {"entity": "epic/KAN-4"})
    paths = [r.path for r in mock_api.requests]
    assert "/audit/entity/epic/epic-1" in paths


def test_get_audit_trail_workspace_reference(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    ``workspace/KAN`` resolves to the workspace UUID.
    """
    mock_api.json("GET", "/workspaces/KAN", body=ws_body("KAN"))
    mock_api.json(
        "GET",
        "/audit/entity/workspace/ws-kan",
        body={"items": []},
    )
    _handler("get_audit_trail")(client, {"entity": "workspace/KAN"})


def test_get_audit_trail_rejects_malformed_entity(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    An ``entity`` without a type prefix is a validation error.
    """
    with pytest.raises(McpApiRequestError) as excinfo:
        _handler("get_audit_trail")(client, {"entity": "KAN-1"})
    assert excinfo.value.code == "validation_error"


def test_get_audit_trail_rejects_unknown_entity_type(
    mock_api: MockApi, client: McpApiClient
) -> None:
    """
    An unsupported ``{type}`` (e.g. 'comment') is a validation error
    because the tool cannot resolve a reference for it.
    """
    with pytest.raises(McpApiRequestError) as excinfo:
        _handler("get_audit_trail")(client, {"entity": "comment/c1"})
    assert excinfo.value.code == "validation_error"
