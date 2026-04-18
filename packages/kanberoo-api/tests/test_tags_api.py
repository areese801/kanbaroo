"""
Integration tests for the ``/api/v1/tags`` REST surface.

Covers workspace-scoped CRUD, collision handling, the no-ETag contract
(tags do not carry a ``version`` column), and the soft-delete-detaches
behaviour at the HTTP level.
"""

from typing import Any

from fastapi.testclient import TestClient


def _create_workspace(
    client: TestClient, human_auth: Any, *, key: str = "KAN"
) -> dict[str, Any]:
    """
    POST a workspace and return the decoded body.
    """
    response = client.post(
        "/api/v1/workspaces",
        json={"key": key, "name": f"{key} workspace"},
        headers=human_auth.headers,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _create_story(
    client: TestClient, human_auth: Any, workspace_id: str
) -> dict[str, Any]:
    """
    POST a story and return the decoded body.
    """
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/stories",
        json={"title": "s"},
        headers=human_auth.headers,
    )
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


def test_create_tag_returns_201_and_location(
    client: TestClient, human_auth: Any
) -> None:
    """
    POST returns 201 with Location. No ETag is sent because tags have
    no version column.
    """
    ws = _create_workspace(client, human_auth)
    response = client.post(
        f"/api/v1/workspaces/{ws['id']}/tags",
        json={"name": "bug", "color": "#cc3333"},
        headers=human_auth.headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "bug"
    assert body["color"] == "#cc3333"
    assert "etag" not in (h.lower() for h in response.headers)
    assert response.headers["location"] == f"/api/v1/tags/{body['id']}"


def test_duplicate_name_rejected(client: TestClient, human_auth: Any) -> None:
    """
    Creating a tag with an existing name in the same workspace returns
    400 ``validation_error``.
    """
    ws = _create_workspace(client, human_auth)
    client.post(
        f"/api/v1/workspaces/{ws['id']}/tags",
        json={"name": "bug"},
        headers=human_auth.headers,
    )
    response = client.post(
        f"/api/v1/workspaces/{ws['id']}/tags",
        json={"name": "bug"},
        headers=human_auth.headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_list_tags_alphabetical(client: TestClient, human_auth: Any) -> None:
    """
    GET returns tags ordered by name.
    """
    ws = _create_workspace(client, human_auth)
    for name in ("zeta", "alpha", "mu"):
        client.post(
            f"/api/v1/workspaces/{ws['id']}/tags",
            json={"name": name},
            headers=human_auth.headers,
        )
    response = client.get(
        f"/api/v1/workspaces/{ws['id']}/tags", headers=human_auth.headers
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert [t["name"] for t in items] == ["alpha", "mu", "zeta"]


def test_patch_tag_without_if_match(client: TestClient, human_auth: Any) -> None:
    """
    PATCH works without ``If-Match`` since tags have no version.
    """
    ws = _create_workspace(client, human_auth)
    tag = client.post(
        f"/api/v1/workspaces/{ws['id']}/tags",
        json={"name": "old"},
        headers=human_auth.headers,
    ).json()
    response = client.patch(
        f"/api/v1/tags/{tag['id']}",
        json={"name": "new", "color": "#123456"},
        headers=human_auth.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "new"
    assert body["color"] == "#123456"


def test_delete_tag_detaches_from_stories(client: TestClient, human_auth: Any) -> None:
    """
    Deleting a tag removes its association from every story in the
    same request (and returns 204 without If-Match).
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"])
    tag = client.post(
        f"/api/v1/workspaces/{ws['id']}/tags",
        json={"name": "bug"},
        headers=human_auth.headers,
    ).json()
    # Attach via the story endpoint.
    attach = client.post(
        f"/api/v1/stories/{story['id']}/tags",
        json={"tag_ids": [tag["id"]]},
        headers=human_auth.headers,
    )
    assert attach.status_code == 200

    response = client.delete(f"/api/v1/tags/{tag['id']}", headers=human_auth.headers)
    assert response.status_code == 204

    # Confirm filtering by the deleted tag's name returns empty.
    filtered = client.get(
        f"/api/v1/workspaces/{ws['id']}/stories?tag=bug",
        headers=human_auth.headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()["items"] == []


def test_cross_workspace_tagging_rejected_at_api(
    client: TestClient, human_auth: Any
) -> None:
    """
    Attaching a tag from workspace B to a story in workspace A returns
    400 ``validation_error``.
    """
    ws_a = _create_workspace(client, human_auth, key="AAA")
    ws_b = _create_workspace(client, human_auth, key="BBB")
    story_a = _create_story(client, human_auth, ws_a["id"])
    tag_b = client.post(
        f"/api/v1/workspaces/{ws_b['id']}/tags",
        json={"name": "b"},
        headers=human_auth.headers,
    ).json()

    response = client.post(
        f"/api/v1/stories/{story_a['id']}/tags",
        json={"tag_ids": [tag_b["id"]]},
        headers=human_auth.headers,
    )
    assert response.status_code == 400


def test_similar_tags_endpoint_empty_and_match(
    client: TestClient, human_auth: Any
) -> None:
    """
    ``GET /workspaces/{id}/tags/similar`` returns an empty list when
    nothing matches and the matching tag when one does. Casing and
    punctuation differences still match.
    """
    ws = _create_workspace(client, human_auth)
    empty = client.get(
        f"/api/v1/workspaces/{ws['id']}/tags/similar?name=Anything",
        headers=human_auth.headers,
    )
    assert empty.status_code == 200
    assert empty.json() == {"items": []}

    tag = client.post(
        f"/api/v1/workspaces/{ws['id']}/tags",
        json={"name": "UI"},
        headers=human_auth.headers,
    ).json()
    matched = client.get(
        f"/api/v1/workspaces/{ws['id']}/tags/similar",
        params={"name": "u-i"},
        headers=human_auth.headers,
    )
    assert matched.status_code == 200
    assert [t["id"] for t in matched.json()["items"]] == [tag["id"]]


def test_similar_tags_requires_auth(client: TestClient) -> None:
    """
    The endpoint refuses unauthenticated callers.
    """
    response = client.get("/api/v1/workspaces/anything/tags/similar?name=x")
    assert response.status_code == 401
