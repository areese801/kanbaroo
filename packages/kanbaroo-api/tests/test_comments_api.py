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


def _post_comment(
    client: TestClient, human_auth: Any, story_id: str, body: str
) -> dict[str, Any]:
    """
    POST a comment and return the decoded body.
    """
    response = client.post(
        f"/api/v1/stories/{story_id}/comments",
        json={"body": body},
        headers=human_auth.headers,
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def test_list_workspace_comments_returns_all_live_comments(
    client: TestClient, human_auth: Any
) -> None:
    """
    ``GET /workspaces/{id}/comments`` returns every live comment across
    the workspace's live stories in a ``{items, next_cursor}`` envelope,
    ordered by comment id.
    """
    ws = _create_workspace(client, human_auth)
    s1 = _create_story(client, human_auth, ws["id"])
    s2 = _create_story(client, human_auth, ws["id"])
    c1 = _post_comment(client, human_auth, s1["id"], "one")
    c2 = _post_comment(client, human_auth, s2["id"], "two")

    response = client.get(
        f"/api/v1/workspaces/{ws['id']}/comments", headers=human_auth.headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["next_cursor"] is None
    assert [item["id"] for item in body["items"]] == sorted([c1["id"], c2["id"]])
    assert {item["story_id"] for item in body["items"]} == {s1["id"], s2["id"]}
    assert "ETag" not in response.headers


def test_list_workspace_comments_paginates(client: TestClient, human_auth: Any) -> None:
    """
    ``limit`` and ``cursor`` walk the collection without gaps or repeats.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"])
    ids = [
        _post_comment(client, human_auth, story["id"], f"c{n}")["id"] for n in range(5)
    ]

    seen: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get(
            f"/api/v1/workspaces/{ws['id']}/comments",
            params=params,
            headers=human_auth.headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) <= 2
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert seen == sorted(ids)


def test_list_workspace_comments_rejects_out_of_range_limit(
    client: TestClient, human_auth: Any
) -> None:
    """
    ``limit`` outside ``[1, 200]`` is a 400 at the API layer, matching
    the story list endpoint.
    """
    ws = _create_workspace(client, human_auth)
    response = client.get(
        f"/api/v1/workspaces/{ws['id']}/comments",
        params={"limit": 201},
        headers=human_auth.headers,
    )
    assert response.status_code == 400


def test_list_workspace_comments_scoped_to_workspace(
    client: TestClient, human_auth: Any
) -> None:
    """
    Comments belonging to another workspace never appear.
    """
    ws_a = _create_workspace(client, human_auth)
    response = client.post(
        "/api/v1/workspaces",
        json={"key": "OTH", "name": "Other"},
        headers=human_auth.headers,
    )
    assert response.status_code == 201
    ws_b = response.json()
    story_a = _create_story(client, human_auth, ws_a["id"])
    story_b = _create_story(client, human_auth, ws_b["id"])
    _post_comment(client, human_auth, story_a["id"], "a")
    _post_comment(client, human_auth, story_b["id"], "b")

    body = client.get(
        f"/api/v1/workspaces/{ws_a['id']}/comments", headers=human_auth.headers
    ).json()

    assert [item["body"] for item in body["items"]] == ["a"]


def test_list_workspace_comments_excludes_soft_deleted(
    client: TestClient, human_auth: Any
) -> None:
    """
    Soft-deleted comments and comments on soft-deleted stories are
    both excluded.
    """
    ws = _create_workspace(client, human_auth)
    live_story = _create_story(client, human_auth, ws["id"])
    dead_story = _create_story(client, human_auth, ws["id"])
    keep = _post_comment(client, human_auth, live_story["id"], "keep")
    gone = _post_comment(client, human_auth, live_story["id"], "gone")
    _post_comment(client, human_auth, dead_story["id"], "orphaned")
    assert (
        client.delete(
            f"/api/v1/comments/{gone['id']}",
            headers={**human_auth.headers, "If-Match": "1"},
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/v1/stories/{dead_story['id']}",
            headers={**human_auth.headers, "If-Match": "1"},
        ).status_code
        == 204
    )

    body = client.get(
        f"/api/v1/workspaces/{ws['id']}/comments", headers=human_auth.headers
    ).json()

    assert [item["id"] for item in body["items"]] == [keep["id"]]


def test_list_workspace_comments_unknown_workspace_404(
    client: TestClient, human_auth: Any
) -> None:
    """
    An unknown workspace returns the canonical 404 envelope with
    ``entity_type: workspace`` in the details. Clients rely on that
    detail to tell a missing workspace apart from a server that does
    not have this route at all.
    """
    response = client.get(
        "/api/v1/workspaces/missing/comments", headers=human_auth.headers
    )
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["details"] == {"entity_type": "workspace", "entity_id": "missing"}


def test_list_workspace_comments_requires_auth(client: TestClient) -> None:
    """
    No bearer token means 401, like every other endpoint.
    """
    response = client.get("/api/v1/workspaces/anything/comments")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_unknown_route_404_has_no_entity_details(
    client: TestClient, human_auth: Any
) -> None:
    """
    Pin the shape a client sees from a server that lacks a route: the
    framework 404 carries ``details: null``. The TUI's bulk-comments
    fallback keys off this difference, so a change here must be
    reflected in ``kanbaroo_tui.search_index``.
    """
    response = client.get(
        "/api/v1/workspaces/anything/no-such-collection",
        headers=human_auth.headers,
    )
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["details"] is None
