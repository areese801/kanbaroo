"""
Integration tests for the ``/api/v1/epics`` REST surface.

Covers the list/create paths scoped to a workspace, the id-addressed
read/update/delete/close/reopen endpoints, and the load-bearing audit
invariant: every mutation writes one ``audit_events`` row attributed
to the caller.
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
    name: str = "Kanberoo",
) -> dict[str, Any]:
    """
    POST a workspace and return the decoded JSON body.
    """
    response = client.post(
        "/api/v1/workspaces",
        json={"key": key, "name": name},
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
    title: str = "v1",
    description: str | None = None,
) -> dict[str, Any]:
    """
    POST an epic and return the decoded JSON body.
    """
    payload: dict[str, Any] = {"title": title}
    if description is not None:
        payload["description"] = description
    response = client.post(
        f"/api/v1/workspaces/{workspace_id}/epics",
        json=payload,
        headers=human_auth.headers,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_create_epic_returns_201_etag_and_location(
    client: TestClient, human_auth: Any
) -> None:
    """
    A successful POST returns 201, ETag ``1``, and a Location header.
    """
    ws = _create_workspace(client, human_auth)
    response = client.post(
        f"/api/v1/workspaces/{ws['id']}/epics",
        json={"title": "release"},
        headers=human_auth.headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "release"
    assert body["state"] == "open"
    assert body["human_id"] == "KAN-1"
    assert body["version"] == 1
    assert response.headers["etag"] == "1"
    assert response.headers["location"] == f"/api/v1/epics/{body['id']}"


def test_get_epic_echoes_etag_and_body(client: TestClient, human_auth: Any) -> None:
    """
    Reading an epic returns the current version via ETag.
    """
    ws = _create_workspace(client, human_auth)
    epic = _create_epic(client, human_auth, ws["id"])
    response = client.get(f"/api/v1/epics/{epic['id']}", headers=human_auth.headers)
    assert response.status_code == 200
    assert response.headers["etag"] == "1"
    assert response.json()["id"] == epic["id"]


def test_patch_epic_bumps_version(client: TestClient, human_auth: Any) -> None:
    """
    PATCH with a matching ``If-Match`` bumps the version and advances
    the ETag.
    """
    ws = _create_workspace(client, human_auth)
    epic = _create_epic(client, human_auth, ws["id"])
    response = client.patch(
        f"/api/v1/epics/{epic['id']}",
        json={"title": "release v1.0"},
        headers={**human_auth.headers, "If-Match": "1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "release v1.0"
    assert body["version"] == 2
    assert response.headers["etag"] == "2"


def test_patch_epic_stale_if_match_returns_412(
    client: TestClient, human_auth: Any
) -> None:
    """
    A stale ``If-Match`` returns 412 with the canonical error envelope.
    """
    ws = _create_workspace(client, human_auth)
    epic = _create_epic(client, human_auth, ws["id"])
    response = client.patch(
        f"/api/v1/epics/{epic['id']}",
        json={"title": "no"},
        headers={**human_auth.headers, "If-Match": "99"},
    )
    assert response.status_code == 412
    body = response.json()
    assert body["error"]["code"] == "version_conflict"
    assert body["error"]["details"]["expected_version"] == 99
    assert body["error"]["details"]["actual_version"] == 1


def test_patch_epic_missing_if_match_is_400(
    client: TestClient, human_auth: Any
) -> None:
    """
    PATCH without ``If-Match`` is rejected with ``missing_if_match``.
    """
    ws = _create_workspace(client, human_auth)
    epic = _create_epic(client, human_auth, ws["id"])
    response = client.patch(
        f"/api/v1/epics/{epic['id']}",
        json={"title": "x"},
        headers=human_auth.headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_if_match"


def test_delete_soft_deletes_and_include_deleted_returns_row(
    client: TestClient, human_auth: Any
) -> None:
    """
    DELETE returns 204 and the row then 404s on default reads but is
    retrievable via ``?include_deleted=true``.
    """
    ws = _create_workspace(client, human_auth)
    epic = _create_epic(client, human_auth, ws["id"])
    response = client.delete(
        f"/api/v1/epics/{epic['id']}",
        headers={**human_auth.headers, "If-Match": "1"},
    )
    assert response.status_code == 204

    response = client.get(f"/api/v1/epics/{epic['id']}", headers=human_auth.headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"

    response = client.get(
        f"/api/v1/epics/{epic['id']}?include_deleted=true",
        headers=human_auth.headers,
    )
    assert response.status_code == 200
    assert response.json()["deleted_at"] is not None


def test_close_endpoint_transitions_and_is_idempotent(
    client: TestClient, human_auth: Any
) -> None:
    """
    ``POST /epics/{id}/close`` sets state to ``closed``; a second
    call with the current version is a no-op (same version returned).
    """
    ws = _create_workspace(client, human_auth)
    epic = _create_epic(client, human_auth, ws["id"])

    first = client.post(
        f"/api/v1/epics/{epic['id']}/close",
        headers={**human_auth.headers, "If-Match": "1"},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["state"] == "closed"
    assert body["version"] == 2

    second = client.post(
        f"/api/v1/epics/{epic['id']}/close",
        headers={**human_auth.headers, "If-Match": "2"},
    )
    assert second.status_code == 200
    assert second.json()["version"] == 2


def test_reopen_endpoint_restores_open_state(
    client: TestClient, human_auth: Any
) -> None:
    """
    After close, reopen returns the epic to ``state=open``.
    """
    ws = _create_workspace(client, human_auth)
    epic = _create_epic(client, human_auth, ws["id"])
    client.post(
        f"/api/v1/epics/{epic['id']}/close",
        headers={**human_auth.headers, "If-Match": "1"},
    )
    response = client.post(
        f"/api/v1/epics/{epic['id']}/reopen",
        headers={**human_auth.headers, "If-Match": "2"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "open"
    assert body["version"] == 3


def test_list_epics_scoped_to_workspace_and_paginates(
    client: TestClient, human_auth: Any
) -> None:
    """
    List returns only epics in the requested workspace and follows a
    cursor across multiple pages.
    """
    ws_a = _create_workspace(client, human_auth, key="AAA", name="A")
    ws_b = _create_workspace(client, human_auth, key="BBB", name="B")
    for i in range(5):
        _create_epic(client, human_auth, ws_a["id"], title=f"a{i}")
    for i in range(3):
        _create_epic(client, human_auth, ws_b["id"], title=f"b{i}")

    seen_a: list[str] = []
    cursor: str | None = None
    while True:
        url = f"/api/v1/workspaces/{ws_a['id']}/epics?limit=2"
        if cursor is not None:
            url += f"&cursor={cursor}"
        resp = client.get(url, headers=human_auth.headers)
        assert resp.status_code == 200
        body = resp.json()
        seen_a.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen_a) == 5

    b_body = client.get(
        f"/api/v1/workspaces/{ws_b['id']}/epics",
        headers=human_auth.headers,
    ).json()
    assert len(b_body["items"]) == 3


def test_audit_row_per_mutation(
    client: TestClient, human_auth: Any, session: Session
) -> None:
    """
    Create, update, close, reopen, and soft-delete each add exactly
    one audit row attributed to ``human/adam``.
    """
    ws = _create_workspace(client, human_auth)
    epic = _create_epic(client, human_auth, ws["id"])

    client.patch(
        f"/api/v1/epics/{epic['id']}",
        json={"description": "added"},
        headers={**human_auth.headers, "If-Match": "1"},
    )
    client.post(
        f"/api/v1/epics/{epic['id']}/close",
        headers={**human_auth.headers, "If-Match": "2"},
    )
    client.post(
        f"/api/v1/epics/{epic['id']}/reopen",
        headers={**human_auth.headers, "If-Match": "3"},
    )
    client.delete(
        f"/api/v1/epics/{epic['id']}",
        headers={**human_auth.headers, "If-Match": "4"},
    )

    events = (
        session.query(AuditEvent)
        .filter(AuditEvent.entity_id == epic["id"])
        .order_by(AuditEvent.occurred_at, AuditEvent.id)
        .all()
    )
    assert [e.action for e in events] == [
        "created",
        "updated",
        "updated",
        "updated",
        "soft_deleted",
    ]
    for row in events:
        assert row.actor_type == "human"
        assert row.actor_id == "adam"


def test_create_epic_in_unknown_workspace_is_404(
    client: TestClient, human_auth: Any
) -> None:
    """
    POSTing an epic into an unknown workspace returns 404 with the
    canonical error envelope.
    """
    response = client.post(
        "/api/v1/workspaces/nonexistent/epics",
        json={"title": "x"},
        headers=human_auth.headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
