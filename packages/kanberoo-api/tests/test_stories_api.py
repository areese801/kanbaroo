"""
Integration tests for the ``/api/v1/stories`` REST surface.

Covers CRUD, human-id lookup, filter combinations, the transition
endpoint (valid and invalid targets, no-op rejection), cursor
pagination across 150 stories, and the audit invariant on the
transition endpoint.
"""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from kanberoo_core.models.audit import AuditEvent


def _create_workspace(
    client: TestClient,
    human_auth: Any,
    *,
    key: str = "KAN",
) -> dict[str, Any]:
    """
    POST a workspace and return the decoded JSON body.
    """
    response = client.post(
        "/api/v1/workspaces",
        json={"key": key, "name": f"{key} workspace"},
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
    title: str = "e",
) -> dict[str, Any]:
    """
    POST an epic and return the decoded JSON body.
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
    **payload: Any,
) -> dict[str, Any]:
    """
    POST a story and return the decoded JSON body.
    """
    request_body: dict[str, Any] = {"title": payload.pop("title", "s")}
    request_body.update(payload)
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/stories",
        json=request_body,
        headers=human_auth.headers,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_create_story_returns_201_etag_and_location(
    client: TestClient, human_auth: Any
) -> None:
    """
    A successful POST returns 201, ETag ``1``, Location, the starting
    ``backlog`` state, and an allocated human id.
    """
    ws = _create_workspace(client, human_auth)
    response = client.post(
        f"/api/v1/workspaces/{ws['id']}/stories",
        json={"title": "first"},
        headers=human_auth.headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "backlog"
    assert body["human_id"] == "KAN-1"
    assert body["version"] == 1
    assert response.headers["etag"] == "1"
    assert response.headers["location"] == f"/api/v1/stories/{body['id']}"


def test_get_story_and_by_key_roundtrip(client: TestClient, human_auth: Any) -> None:
    """
    Reads by id and by human id return the same story.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"], title="s")
    by_id = client.get(f"/api/v1/stories/{story['id']}", headers=human_auth.headers)
    assert by_id.status_code == 200
    assert by_id.headers["etag"] == "1"

    by_key = client.get(
        f"/api/v1/stories/by-key/{story['human_id']}",
        headers=human_auth.headers,
    )
    assert by_key.status_code == 200
    assert by_key.json()["id"] == story["id"]


def test_patch_story_updates_non_state_fields(
    client: TestClient, human_auth: Any
) -> None:
    """
    PATCH updates title, priority, etc. and advances the ETag.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"], title="s")
    response = client.patch(
        f"/api/v1/stories/{story['id']}",
        json={"title": "renamed", "priority": "high"},
        headers={**human_auth.headers, "If-Match": "1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "renamed"
    assert body["priority"] == "high"
    assert body["version"] == 2


def test_patch_story_stale_if_match_returns_412(
    client: TestClient, human_auth: Any
) -> None:
    """
    Stale ``If-Match`` returns 412 with the canonical envelope.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"])
    response = client.patch(
        f"/api/v1/stories/{story['id']}",
        json={"title": "no"},
        headers={**human_auth.headers, "If-Match": "99"},
    )
    assert response.status_code == 412
    assert response.json()["error"]["code"] == "version_conflict"


def test_soft_delete_and_include_deleted(client: TestClient, human_auth: Any) -> None:
    """
    DELETE returns 204; default reads 404, ``?include_deleted=true``
    returns the row.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"])
    response = client.delete(
        f"/api/v1/stories/{story['id']}",
        headers={**human_auth.headers, "If-Match": "1"},
    )
    assert response.status_code == 204
    after = client.get(f"/api/v1/stories/{story['id']}", headers=human_auth.headers)
    assert after.status_code == 404
    with_deleted = client.get(
        f"/api/v1/stories/{story['id']}?include_deleted=true",
        headers=human_auth.headers,
    )
    assert with_deleted.status_code == 200


def test_transition_endpoint_valid_move(client: TestClient, human_auth: Any) -> None:
    """
    A valid transition succeeds, bumps the version, stamps
    ``state_actor_*``, and echoes the new state in the body.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"])
    response = client.post(
        f"/api/v1/stories/{story['id']}/transition",
        json={"to_state": "todo", "reason": "ready"},
        headers={**human_auth.headers, "If-Match": "1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "todo"
    assert body["version"] == 2
    assert body["state_actor_type"] == "human"
    assert body["state_actor_id"] == "adam"


def test_transition_endpoint_invalid_move_is_400(
    client: TestClient, human_auth: Any
) -> None:
    """
    An invalid transition returns 400 with ``validation_error`` and
    ``from_state``/``to_state`` in the details.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"])
    response = client.post(
        f"/api/v1/stories/{story['id']}/transition",
        json={"to_state": "done"},
        headers={**human_auth.headers, "If-Match": "1"},
    )
    assert response.status_code == 400
    err = response.json()["error"]
    assert err["code"] == "validation_error"
    assert err["details"]["from_state"] == "backlog"
    assert err["details"]["to_state"] == "done"


def test_transition_endpoint_noop_is_rejected(
    client: TestClient, human_auth: Any
) -> None:
    """
    Transitioning to the current state is rejected as invalid.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"])
    response = client.post(
        f"/api/v1/stories/{story['id']}/transition",
        json={"to_state": "backlog"},
        headers={**human_auth.headers, "If-Match": "1"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_transition_writes_state_changed_audit(
    client: TestClient, human_auth: Any, session: Session
) -> None:
    """
    A successful transition writes one audit row with
    ``action="state_changed"`` attributed to the caller.
    """
    ws = _create_workspace(client, human_auth)
    story = _create_story(client, human_auth, ws["id"])
    client.post(
        f"/api/v1/stories/{story['id']}/transition",
        json={"to_state": "todo", "reason": "picked up"},
        headers={**human_auth.headers, "If-Match": "1"},
    )
    rows = (
        session.query(AuditEvent)
        .filter(AuditEvent.entity_id == story["id"])
        .order_by(AuditEvent.occurred_at, AuditEvent.id)
        .all()
    )
    assert [r.action for r in rows] == ["created", "state_changed"]
    for row in rows:
        assert row.actor_type == "human"
        assert row.actor_id == "adam"


def test_create_story_in_other_workspace_epic_returns_400(
    client: TestClient, human_auth: Any
) -> None:
    """
    Supplying an ``epic_id`` from a different workspace is rejected
    at creation time.
    """
    ws_a = _create_workspace(client, human_auth, key="AAA")
    ws_b = _create_workspace(client, human_auth, key="BBB")
    epic_in_a = _create_epic(client, human_auth, ws_a["id"])
    response = client.post(
        f"/api/v1/workspaces/{ws_b['id']}/stories",
        json={"title": "x", "epic_id": epic_in_a["id"]},
        headers=human_auth.headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_list_stories_filters(client: TestClient, human_auth: Any) -> None:
    """
    List returns only stories matching all supplied filters
    (``state``, ``priority``, ``epic_id``).
    """
    ws = _create_workspace(client, human_auth)
    epic = _create_epic(client, human_auth, ws["id"])

    # Target: priority=high + epic set + state=todo.
    target = _create_story(
        client, human_auth, ws["id"], priority="high", epic_id=epic["id"]
    )
    client.post(
        f"/api/v1/stories/{target['id']}/transition",
        json={"to_state": "todo"},
        headers={**human_auth.headers, "If-Match": "1"},
    )

    # Low priority, no epic, still backlog.
    _create_story(client, human_auth, ws["id"], priority="low")

    resp = client.get(
        f"/api/v1/workspaces/{ws['id']}/stories"
        f"?state=todo&priority=high&epic_id={epic['id']}",
        headers=human_auth.headers,
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [s["id"] for s in items] == [target["id"]]


def test_list_stories_paginates_across_150(client: TestClient, human_auth: Any) -> None:
    """
    Creating 150 stories yields three default-page walks that return
    every id exactly once.
    """
    ws = _create_workspace(client, human_auth)
    total = 150
    for i in range(total):
        _create_story(client, human_auth, ws["id"], title=f"s{i:03d}")

    seen: list[str] = []
    cursor: str | None = None
    while True:
        url = f"/api/v1/workspaces/{ws['id']}/stories?limit=50"
        if cursor is not None:
            url += f"&cursor={cursor}"
        resp = client.get(url, headers=human_auth.headers)
        assert resp.status_code == 200
        body = resp.json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == total
    assert len(set(seen)) == total


def test_patch_rejects_cross_workspace_epic_reassignment(
    client: TestClient, human_auth: Any
) -> None:
    """
    PATCH with an ``epic_id`` in a different workspace returns 400.
    """
    ws_a = _create_workspace(client, human_auth, key="AAA")
    ws_b = _create_workspace(client, human_auth, key="BBB")
    epic_in_b = _create_epic(client, human_auth, ws_b["id"])
    story_in_a = _create_story(client, human_auth, ws_a["id"])

    response = client.patch(
        f"/api/v1/stories/{story_in_a['id']}",
        json={"epic_id": epic_in_b["id"]},
        headers={**human_auth.headers, "If-Match": "1"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_unknown_story_returns_404(client: TestClient, human_auth: Any) -> None:
    """
    GET of an unknown id returns 404 with the canonical envelope.
    """
    response = client.get("/api/v1/stories/nonexistent", headers=human_auth.headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_by_key_404_for_unknown_human_id(client: TestClient, human_auth: Any) -> None:
    """
    GET by-key returns 404 for an unknown ``KAN-N`` handle.
    """
    response = client.get("/api/v1/stories/by-key/NOPE-1", headers=human_auth.headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
