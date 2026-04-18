"""
Integration tests for the ``/api/v1/audit`` REST surface.

These cover the wire contract: filter query params, cursor
pagination, the per-entity convenience path, and the
response-body shape with ``diff`` parsed into a structured object.
"""

from typing import Any

from fastapi.testclient import TestClient


def _create_workspace(
    client: TestClient, human_auth: Any, *, key: str = "KAN"
) -> dict[str, Any]:
    """
    POST a workspace and return the decoded JSON body.
    """
    response = client.post(
        "/api/v1/workspaces",
        json={"key": key, "name": key},
        headers=human_auth.headers,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _create_epic(
    client: TestClient,
    human_auth: Any,
    workspace_id: str,
    *,
    title: str = "Epic",
) -> dict[str, Any]:
    """
    Create an epic in ``workspace_id`` and return its body.
    """
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/epics",
        json={"title": title},
        headers=human_auth.headers,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _create_story(
    client: TestClient,
    human_auth: Any,
    workspace_id: str,
    *,
    title: str = "Story",
) -> dict[str, Any]:
    """
    Create a story in ``workspace_id`` and return its body.
    """
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/stories",
        json={"title": title},
        headers=human_auth.headers,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_list_audit_returns_envelope_with_parsed_diff(
    client: TestClient, human_auth: Any
) -> None:
    """
    The list endpoint returns ``{items, next_cursor}`` and the ``diff``
    field is a structured object, not a JSON-encoded string.
    """
    workspace = _create_workspace(client, human_auth)
    _create_epic(client, human_auth, workspace["id"])

    response = client.get("/api/v1/audit", headers=human_auth.headers)
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert "next_cursor" in body
    for item in body["items"]:
        assert isinstance(item["diff"], dict)
        assert "before" in item["diff"]
        assert "after" in item["diff"]


def test_list_audit_filters_by_entity_type(client: TestClient, human_auth: Any) -> None:
    """
    ``entity_type=workspace`` returns only workspace rows.
    """
    workspace = _create_workspace(client, human_auth)
    _create_epic(client, human_auth, workspace["id"])
    _create_story(client, human_auth, workspace["id"])

    response = client.get(
        "/api/v1/audit?entity_type=workspace",
        headers=human_auth.headers,
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    assert all(item["entity_type"] == "workspace" for item in items)


def test_list_audit_filters_by_actor(client: TestClient, human_auth: Any) -> None:
    """
    ``actor_type`` + ``actor_id`` narrows the feed to one actor.
    """
    workspace = _create_workspace(client, human_auth)
    _create_epic(client, human_auth, workspace["id"])

    response = client.get(
        "/api/v1/audit?actor_type=human&actor_id=adam",
        headers=human_auth.headers,
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    for item in items:
        assert item["actor_type"] == "human"
        assert item["actor_id"] == "adam"


def test_list_audit_pagination_walks_large_feed(
    client: TestClient, human_auth: Any
) -> None:
    """
    Emitting 150+ mixed audit rows and walking the cursor surfaces
    every row exactly once.
    """
    workspace = _create_workspace(client, human_auth)
    # Each epic + each story creation emits one audit row; interleave
    # so the feed has a mix of entity types and actions.
    for i in range(50):
        _create_epic(client, human_auth, workspace["id"], title=f"E{i}")
        _create_story(client, human_auth, workspace["id"], title=f"S{i}")
    # Plus the one workspace.created row = 101 rows. Add updates to
    # cross 150. Re-read the workspace each time because every epic
    # and story allocation bumps ``next_issue_num`` and therefore
    # the workspace version.
    current = client.get(
        f"/api/v1/workspaces/{workspace['id']}",
        headers=human_auth.headers,
    )
    etag = current.headers["etag"]
    for i in range(55):
        response = client.patch(
            f"/api/v1/workspaces/{workspace['id']}",
            json={"description": f"round {i}"},
            headers={**human_auth.headers, "If-Match": etag},
        )
        assert response.status_code == 200
        etag = response.headers["etag"]

    seen: set[str] = set()
    cursor: str | None = None
    while True:
        url = "/api/v1/audit?limit=50"
        if cursor is not None:
            url += f"&cursor={cursor}"
        response = client.get(url, headers=human_auth.headers)
        assert response.status_code == 200
        body = response.json()
        for item in body["items"]:
            seen.add(item["id"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) >= 150


def test_list_audit_for_entity_returns_history(
    client: TestClient, human_auth: Any
) -> None:
    """
    The per-entity endpoint returns the create, update, and
    soft-delete rows for a single story.
    """
    workspace = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, workspace["id"])

    transition = client.post(
        f"/api/v1/stories/{story['id']}/transition",
        json={"to_state": "todo"},
        headers={**human_auth.headers, "If-Match": "1"},
    )
    assert transition.status_code == 200

    delete = client.delete(
        f"/api/v1/stories/{story['id']}",
        headers={**human_auth.headers, "If-Match": "2"},
    )
    assert delete.status_code == 204

    response = client.get(
        f"/api/v1/audit/entity/story/{story['id']}",
        headers=human_auth.headers,
    )
    assert response.status_code == 200
    body = response.json()
    actions = [item["action"] for item in body["items"]]
    # Newest-first: soft_deleted, state_changed, created.
    assert actions[0] == "soft_deleted"
    assert "state_changed" in actions
    assert "created" in actions


def test_list_audit_requires_auth(client: TestClient) -> None:
    """
    Unauthenticated ``GET /audit`` requests return 401 in the
    canonical envelope.
    """
    response = client.get("/api/v1/audit")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_list_audit_rejects_unknown_entity_type(
    client: TestClient, human_auth: Any
) -> None:
    """
    An unknown ``entity_type`` query value is rejected at the FastAPI
    layer (enum validation) and rendered through the canonical error
    envelope.
    """
    response = client.get(
        "/api/v1/audit?entity_type=not-a-type",
        headers=human_auth.headers,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "validation_error"
