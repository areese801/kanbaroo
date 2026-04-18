"""
Integration tests for the ``/api/v1/workspaces`` REST surface.

These tests drive the full app through FastAPI's ``TestClient``. They
assert the wire contract: status codes, headers (ETag, Location), the
canonical error shape, optimistic concurrency, cursor pagination, and
the load-bearing audit invariant: every mutation writes an
``audit_events`` row attributed to the caller.
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
    description: str | None = "Self-hosted kanban",
) -> dict[str, Any]:
    """
    POST a workspace and return the decoded JSON body.
    """
    response = client.post(
        "/api/v1/workspaces",
        json={"key": key, "name": name, "description": description},
        headers=human_auth.headers,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_create_returns_201_with_etag_and_location(
    client: TestClient, human_auth: Any
) -> None:
    """
    A successful POST returns 201, an ETag of ``1``, and a Location
    pointing at the new resource.
    """
    response = client.post(
        "/api/v1/workspaces",
        json={"key": "KAN", "name": "Kanberoo", "description": "Self"},
        headers=human_auth.headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["key"] == "KAN"
    assert body["version"] == 1
    assert response.headers["etag"] == "1"
    assert response.headers["location"] == f"/api/v1/workspaces/{body['id']}"


def test_get_returns_etag_and_body(client: TestClient, human_auth: Any) -> None:
    """
    Reading a workspace echoes its ETag and full schema.
    """
    created = _create_workspace(client, human_auth)
    response = client.get(
        f"/api/v1/workspaces/{created['id']}",
        headers=human_auth.headers,
    )
    assert response.status_code == 200
    assert response.headers["etag"] == "1"
    assert response.json()["id"] == created["id"]


def test_patch_with_matching_if_match_bumps_version(
    client: TestClient, human_auth: Any
) -> None:
    """
    PATCH with the current version succeeds and the ETag advances.
    """
    created = _create_workspace(client, human_auth)
    response = client.patch(
        f"/api/v1/workspaces/{created['id']}",
        json={"name": "Kanberoo Renamed"},
        headers={**human_auth.headers, "If-Match": "1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Kanberoo Renamed"
    assert body["version"] == 2
    assert response.headers["etag"] == "2"


def test_patch_with_stale_if_match_returns_412(
    client: TestClient, human_auth: Any
) -> None:
    """
    A stale ``If-Match`` returns 412 in the canonical error envelope.
    """
    created = _create_workspace(client, human_auth)
    response = client.patch(
        f"/api/v1/workspaces/{created['id']}",
        json={"name": "Will not apply"},
        headers={**human_auth.headers, "If-Match": "99"},
    )
    assert response.status_code == 412
    body = response.json()
    assert body["error"]["code"] == "version_conflict"
    assert body["error"]["details"]["expected_version"] == 99
    assert body["error"]["details"]["actual_version"] == 1


def test_patch_missing_if_match_is_400(client: TestClient, human_auth: Any) -> None:
    """
    PATCH without ``If-Match`` is rejected at 400 with ``missing_if_match``.
    """
    created = _create_workspace(client, human_auth)
    response = client.patch(
        f"/api/v1/workspaces/{created['id']}",
        json={"name": "x"},
        headers=human_auth.headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_if_match"


def test_delete_soft_deletes_and_subsequent_get_is_404(
    client: TestClient, human_auth: Any
) -> None:
    """
    DELETE returns 204 and the row then 404s on default reads but is
    retrievable via ``?include_deleted=true``.
    """
    created = _create_workspace(client, human_auth)
    response = client.delete(
        f"/api/v1/workspaces/{created['id']}",
        headers={**human_auth.headers, "If-Match": "1"},
    )
    assert response.status_code == 204

    response = client.get(
        f"/api/v1/workspaces/{created['id']}",
        headers=human_auth.headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"

    response = client.get(
        f"/api/v1/workspaces/{created['id']}?include_deleted=true",
        headers=human_auth.headers,
    )
    assert response.status_code == 200
    assert response.json()["deleted_at"] is not None


def test_duplicate_key_returns_400(client: TestClient, human_auth: Any) -> None:
    """
    Creating a second workspace with the same key returns 400 with the
    ``validation_error`` code.
    """
    _create_workspace(client, human_auth, key="KAN")
    response = client.post(
        "/api/v1/workspaces",
        json={"key": "KAN", "name": "Dupe"},
        headers=human_auth.headers,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["details"]["field"] == "key"


def test_list_paginates_with_cursor(client: TestClient, human_auth: Any) -> None:
    """
    Creating more rows than the default page size yields pagination;
    following ``next_cursor`` walks the entire list without duplicates.
    """
    total = 150
    for i in range(total):
        _create_workspace(client, human_auth, key=f"WS{i:03d}", name=f"WS {i}")

    seen: list[str] = []
    cursor: str | None = None
    while True:
        url = "/api/v1/workspaces?limit=50"
        if cursor is not None:
            url += f"&cursor={cursor}"
        response = client.get(url, headers=human_auth.headers)
        assert response.status_code == 200
        body = response.json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == total
    assert len(set(seen)) == total


def test_missing_authorization_returns_401(
    client: TestClient,
) -> None:
    """
    Listing without an ``Authorization`` header returns 401.
    """
    response = client.get("/api/v1/workspaces")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_bogus_bearer_returns_401(
    client: TestClient,
) -> None:
    """
    A syntactically-valid but unknown bearer token returns 401.
    """
    response = client.get(
        "/api/v1/workspaces",
        headers={"Authorization": "Bearer kbr_not-a-real-token"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_every_mutation_writes_one_audit_row(
    client: TestClient,
    human_auth: Any,
    session: Session,
) -> None:
    """
    Create, update, and soft-delete each add exactly one audit row
    attributed to ``human/adam`` with the expected action.
    """
    created = _create_workspace(client, human_auth)
    client.patch(
        f"/api/v1/workspaces/{created['id']}",
        json={"description": "Updated"},
        headers={**human_auth.headers, "If-Match": "1"},
    )
    client.delete(
        f"/api/v1/workspaces/{created['id']}",
        headers={**human_auth.headers, "If-Match": "2"},
    )

    events = (
        session.query(AuditEvent)
        .filter(AuditEvent.entity_id == created["id"])
        .order_by(AuditEvent.occurred_at, AuditEvent.id)
        .all()
    )
    assert [e.action for e in events] == ["created", "updated", "soft_deleted"]
    for row in events:
        assert row.actor_type == "human"
        assert row.actor_id == "adam"


def test_get_workspace_by_key_roundtrip_and_404(
    client: TestClient, human_auth: Any
) -> None:
    """
    ``GET /workspaces/by-key/{key}`` returns the full body + ETag for
    a known key, 404s for an unknown one, and round-trips to the same
    row returned by the id-based read.
    """
    created = _create_workspace(client, human_auth, key="KAN")

    response = client.get(
        "/api/v1/workspaces/by-key/KAN",
        headers=human_auth.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["key"] == "KAN"
    assert response.headers["etag"] == "1"

    missing = client.get(
        "/api/v1/workspaces/by-key/NOPE",
        headers=human_auth.headers,
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_get_workspace_by_key_hides_soft_deleted(
    client: TestClient, human_auth: Any
) -> None:
    """
    Soft-deleted workspaces 404 on ``by-key`` by default and become
    visible with ``?include_deleted=true``.
    """
    created = _create_workspace(client, human_auth, key="KAN")
    client.delete(
        f"/api/v1/workspaces/{created['id']}",
        headers={**human_auth.headers, "If-Match": "1"},
    )

    missing = client.get(
        "/api/v1/workspaces/by-key/KAN",
        headers=human_auth.headers,
    )
    assert missing.status_code == 404

    visible = client.get(
        "/api/v1/workspaces/by-key/KAN?include_deleted=true",
        headers=human_auth.headers,
    )
    assert visible.status_code == 200
    assert visible.json()["id"] == created["id"]


def test_export_endpoint_streams_archive(client: TestClient, human_auth: Any) -> None:
    """
    ``GET /workspaces/{id}/export`` streams a ``application/gzip``
    archive with a download-friendly filename header.
    """
    import io
    import tarfile

    created = _create_workspace(client, human_auth, key="KAN")
    response = client.get(
        f"/api/v1/workspaces/{created['id']}/export",
        headers=human_auth.headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/gzip")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert "KAN-export-" in disposition

    archive = response.content
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
        names = {m.name for m in tf.getmembers()}
    assert "schema_version.json" in names
    assert "kanberoo.db" in names
    assert "tables/workspaces.parquet" in names


def test_export_endpoint_requires_auth(client: TestClient, human_auth: Any) -> None:
    """
    Unauthenticated export requests are rejected at 401.
    """
    created = _create_workspace(client, human_auth, key="KAN")
    response = client.get(f"/api/v1/workspaces/{created['id']}/export")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_include_deleted_list_filter(client: TestClient, human_auth: Any) -> None:
    """
    The list endpoint hides soft-deleted rows by default and shows them
    with ``?include_deleted=true``.
    """
    created = _create_workspace(client, human_auth)
    client.delete(
        f"/api/v1/workspaces/{created['id']}",
        headers={**human_auth.headers, "If-Match": "1"},
    )

    default = client.get("/api/v1/workspaces", headers=human_auth.headers).json()
    assert [item["id"] for item in default["items"]] == []

    with_deleted = client.get(
        "/api/v1/workspaces?include_deleted=true",
        headers=human_auth.headers,
    ).json()
    assert [item["id"] for item in with_deleted["items"]] == [created["id"]]
