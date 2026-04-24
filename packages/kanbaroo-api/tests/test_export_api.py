"""
Integration tests for ``GET /api/v1/workspaces/{id}/export``.

Smoke-tests the streaming archive on a fully running FastAPI app.
Deeper assertions on archive contents live in
``packages/kanbaroo-core/tests/test_services_export.py``.
"""

import io
import json
import tarfile
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
        json={"key": key, "name": key},
        headers=human_auth.headers,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_export_endpoint_returns_gzip_archive(
    client: TestClient, human_auth: Any
) -> None:
    """
    A 200 response with ``application/gzip``, a valid tarball body,
    and a manifest referencing the workspace.
    """
    created = _create_workspace(client, human_auth, key="KAN")
    response = client.get(
        f"/api/v1/workspaces/{created['id']}/export",
        headers=human_auth.headers,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/gzip")
    assert "KAN-export-" in response.headers["content-disposition"]

    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as tf:
        names = {m.name for m in tf.getmembers()}
        assert "schema_version.json" in names
        manifest_member = tf.extractfile("schema_version.json")
        assert manifest_member is not None
        manifest = json.loads(manifest_member.read().decode("utf-8"))
    assert manifest["workspace_id"] == created["id"]
    assert manifest["workspace_key"] == "KAN"


def test_export_unknown_id_returns_404(client: TestClient, human_auth: Any) -> None:
    """
    The export endpoint returns the canonical 404 envelope for an
    unknown workspace id.
    """
    response = client.get(
        "/api/v1/workspaces/does-not-exist/export",
        headers=human_auth.headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_export_unauthenticated_is_401(client: TestClient, human_auth: Any) -> None:
    """
    The export endpoint refuses unauthenticated callers at 401 before
    any archive is built.
    """
    created = _create_workspace(client, human_auth, key="KAN")
    response = client.get(f"/api/v1/workspaces/{created['id']}/export")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
