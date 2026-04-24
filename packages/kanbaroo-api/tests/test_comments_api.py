"""
Integration tests for the ``/api/v1/comments`` REST surface.

Covers create/read/update/soft-delete, threading enforcement, and the
ETag / If-Match contract.
"""

from typing import Any

from fastapi.testclient import TestClient


def _create_workspace(client: TestClient, human_auth: Any) -> dict[str, Any]:
    """
    POST a workspace and return the decoded body.
    """
    response = client.post(
        "/api/v1/workspaces",
        json={"key": "KAN", "name": "Kanbaroo"},
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
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_create_comment_returns_201_etag_and_location(
    client: TestClient, human_auth: Any
) -> None:
    """
    A successful POST returns 201, ETag ``1``, Location, and the
    stamped actor.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"])
    response = client.post(
        f"/api/v1/stories/{story['id']}/comments",
        json={"body": "hello"},
        headers=human_auth.headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["body"] == "hello"
    assert body["actor_type"] == "human"
    assert body["actor_id"] == "adam"
    assert response.headers["etag"] == "1"
    assert response.headers["location"] == f"/api/v1/comments/{body['id']}"


def test_list_comments_returns_chronological(
    client: TestClient, human_auth: Any
) -> None:
    """
    GET returns a flat chronological list.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"])
    for body in ("a", "b", "c"):
        client.post(
            f"/api/v1/stories/{story['id']}/comments",
            json={"body": body},
            headers=human_auth.headers,
        )
    response = client.get(
        f"/api/v1/stories/{story['id']}/comments", headers=human_auth.headers
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert [c["body"] for c in items] == ["a", "b", "c"]


def test_reply_to_reply_rejected_at_api(client: TestClient, human_auth: Any) -> None:
    """
    Posting a reply to a reply returns 400 ``validation_error``.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"])
    top = client.post(
        f"/api/v1/stories/{story['id']}/comments",
        json={"body": "top"},
        headers=human_auth.headers,
    ).json()
    reply = client.post(
        f"/api/v1/stories/{story['id']}/comments",
        json={"body": "reply", "parent_id": top["id"]},
        headers=human_auth.headers,
    ).json()

    response = client.post(
        f"/api/v1/stories/{story['id']}/comments",
        json={"body": "nested", "parent_id": reply["id"]},
        headers=human_auth.headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_patch_comment_updates_body(client: TestClient, human_auth: Any) -> None:
    """
    PATCH updates body and bumps version; requires If-Match.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"])
    comment = client.post(
        f"/api/v1/stories/{story['id']}/comments",
        json={"body": "before"},
        headers=human_auth.headers,
    ).json()
    response = client.patch(
        f"/api/v1/comments/{comment['id']}",
        json={"body": "after"},
        headers={**human_auth.headers, "If-Match": "1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["body"] == "after"
    assert body["version"] == 2


def test_patch_comment_stale_if_match_412(client: TestClient, human_auth: Any) -> None:
    """
    Stale ``If-Match`` returns 412 with the canonical envelope.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"])
    comment = client.post(
        f"/api/v1/stories/{story['id']}/comments",
        json={"body": "x"},
        headers=human_auth.headers,
    ).json()
    response = client.patch(
        f"/api/v1/comments/{comment['id']}",
        json={"body": "y"},
        headers={**human_auth.headers, "If-Match": "99"},
    )
    assert response.status_code == 412
    assert response.json()["error"]["code"] == "version_conflict"


def test_delete_comment_soft_deletes(client: TestClient, human_auth: Any) -> None:
    """
    DELETE returns 204; subsequent GET returns 404.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"])
    comment = client.post(
        f"/api/v1/stories/{story['id']}/comments",
        json={"body": "x"},
        headers=human_auth.headers,
    ).json()
    response = client.delete(
        f"/api/v1/comments/{comment['id']}",
        headers={**human_auth.headers, "If-Match": "1"},
    )
    assert response.status_code == 204

    after = client.get(f"/api/v1/comments/{comment['id']}", headers=human_auth.headers)
    assert after.status_code == 404


def test_unknown_story_for_comment_create_returns_404(
    client: TestClient, human_auth: Any
) -> None:
    """
    Creating a comment on a missing story returns 404 ``not_found``.
    """
    response = client.post(
        "/api/v1/stories/missing/comments",
        json={"body": "x"},
        headers=human_auth.headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
