"""
Integration tests for the ``/api/v1/linkages`` REST surface.

Covers create (including the auto-mirror for ``blocks`` pairs), the
story-scoped list endpoint returning both in+out directions, and the
soft-delete cascade on blocking pairs.
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
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_create_blocks_linkage_mirrors_visible_on_both_stories(
    client: TestClient, human_auth: Any
) -> None:
    """
    After posting a ``blocks`` linkage, the source story shows both
    outgoing and incoming rows (forward + mirror) and so does the
    target.
    """
    ws = _create_workspace(client, human_auth)
    a = _create_story(client, human_auth, ws["id"])
    b = _create_story(client, human_auth, ws["id"])

    response = client.post(
        "/api/v1/linkages",
        json={
            "source_type": "story",
            "source_id": a["id"],
            "target_type": "story",
            "target_id": b["id"],
            "link_type": "blocks",
        },
        headers=human_auth.headers,
    )
    assert response.status_code == 201
    forward = response.json()
    assert forward["link_type"] == "blocks"
    assert response.headers["location"] == f"/api/v1/linkages/{forward['id']}"

    a_view = client.get(
        f"/api/v1/stories/{a['id']}/linkages", headers=human_auth.headers
    ).json()["items"]
    b_view = client.get(
        f"/api/v1/stories/{b['id']}/linkages", headers=human_auth.headers
    ).json()["items"]

    assert {li["link_type"] for li in a_view} == {"blocks", "is_blocked_by"}
    assert {li["link_type"] for li in b_view} == {"blocks", "is_blocked_by"}


def test_relates_to_is_unidirectional(client: TestClient, human_auth: Any) -> None:
    """
    ``relates_to`` does not auto-mirror; only one row is written.
    """
    ws = _create_workspace(client, human_auth)
    a = _create_story(client, human_auth, ws["id"])
    b = _create_story(client, human_auth, ws["id"])

    response = client.post(
        "/api/v1/linkages",
        json={
            "source_type": "story",
            "source_id": a["id"],
            "target_type": "story",
            "target_id": b["id"],
            "link_type": "relates_to",
        },
        headers=human_auth.headers,
    )
    assert response.status_code == 201
    a_view = client.get(
        f"/api/v1/stories/{a['id']}/linkages", headers=human_auth.headers
    ).json()["items"]
    b_view = client.get(
        f"/api/v1/stories/{b['id']}/linkages", headers=human_auth.headers
    ).json()["items"]
    assert len(a_view) == 1
    assert len(b_view) == 1
    assert a_view[0]["id"] == b_view[0]["id"]


def test_self_linkage_rejected(client: TestClient, human_auth: Any) -> None:
    """
    A linkage where source == target returns 400.
    """
    ws = _create_workspace(client, human_auth)
    a = _create_story(client, human_auth, ws["id"])
    response = client.post(
        "/api/v1/linkages",
        json={
            "source_type": "story",
            "source_id": a["id"],
            "target_type": "story",
            "target_id": a["id"],
            "link_type": "relates_to",
        },
        headers=human_auth.headers,
    )
    assert response.status_code == 400


def test_duplicate_linkage_rejected(client: TestClient, human_auth: Any) -> None:
    """
    Creating the same linkage twice returns 400.
    """
    ws = _create_workspace(client, human_auth)
    a = _create_story(client, human_auth, ws["id"])
    b = _create_story(client, human_auth, ws["id"])
    payload = {
        "source_type": "story",
        "source_id": a["id"],
        "target_type": "story",
        "target_id": b["id"],
        "link_type": "relates_to",
    }
    first = client.post("/api/v1/linkages", json=payload, headers=human_auth.headers)
    assert first.status_code == 201
    second = client.post("/api/v1/linkages", json=payload, headers=human_auth.headers)
    assert second.status_code == 400


def test_delete_linkage_cascades_to_mirror(client: TestClient, human_auth: Any) -> None:
    """
    Deleting a ``blocks`` linkage also soft-deletes its mirror; both
    endpoints see the linkage list shrink to empty.
    """
    ws = _create_workspace(client, human_auth)
    a = _create_story(client, human_auth, ws["id"])
    b = _create_story(client, human_auth, ws["id"])
    forward = client.post(
        "/api/v1/linkages",
        json={
            "source_type": "story",
            "source_id": a["id"],
            "target_type": "story",
            "target_id": b["id"],
            "link_type": "blocks",
        },
        headers=human_auth.headers,
    ).json()

    response = client.delete(
        f"/api/v1/linkages/{forward['id']}", headers=human_auth.headers
    )
    assert response.status_code == 204

    a_view = client.get(
        f"/api/v1/stories/{a['id']}/linkages", headers=human_auth.headers
    ).json()["items"]
    b_view = client.get(
        f"/api/v1/stories/{b['id']}/linkages", headers=human_auth.headers
    ).json()["items"]
    assert a_view == []
    assert b_view == []


def test_cross_workspace_linkage_allowed(client: TestClient, human_auth: Any) -> None:
    """
    A linkage between stories in different workspaces is accepted.
    """
    ws_a = _create_workspace(client, human_auth, key="AAA")
    ws_b = _create_workspace(client, human_auth, key="BBB")
    a = _create_story(client, human_auth, ws_a["id"])
    b = _create_story(client, human_auth, ws_b["id"])
    response = client.post(
        "/api/v1/linkages",
        json={
            "source_type": "story",
            "source_id": a["id"],
            "target_type": "story",
            "target_id": b["id"],
            "link_type": "relates_to",
        },
        headers=human_auth.headers,
    )
    assert response.status_code == 201
