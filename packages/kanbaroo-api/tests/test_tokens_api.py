"""
Integration tests for the ``/api/v1/tokens`` REST surface.

The token resource is the only one in v1 that is **not** audited. These
tests assert the positive paths (create returns plaintext, list masks
it, revoke works) and the negative invariant (``audit_events`` stays
empty through every token operation).
"""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from kanbaroo_core.models.api_token import ApiToken
from kanbaroo_core.models.audit import AuditEvent


def test_create_token_returns_plaintext_once(
    client: TestClient, human_auth: Any
) -> None:
    """
    POST /tokens returns the plaintext in the response body; subsequent
    GETs of the same collection do not include it.
    """
    response = client.post(
        "/api/v1/tokens",
        json={"actor_type": "claude", "actor_id": "outer-claude", "name": "mcp"},
        headers=human_auth.headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["plaintext"].startswith("kbr_")
    assert body["name"] == "mcp"

    list_response = client.get("/api/v1/tokens", headers=human_auth.headers)
    assert list_response.status_code == 200
    for row in list_response.json():
        assert "plaintext" not in row


def test_revoke_token_returns_204_and_denies_auth(
    client: TestClient, human_auth: Any
) -> None:
    """
    A revoked token can no longer be used to authenticate.
    """
    created = client.post(
        "/api/v1/tokens",
        json={"actor_type": "human", "actor_id": "adam", "name": "throwaway"},
        headers=human_auth.headers,
    ).json()

    revoke = client.delete(
        f"/api/v1/tokens/{created['id']}", headers=human_auth.headers
    )
    assert revoke.status_code == 204

    ping = client.get(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {created['plaintext']}"},
    )
    assert ping.status_code == 401


def test_revoke_unknown_token_is_404(client: TestClient, human_auth: Any) -> None:
    """
    Revoking a completely unknown id returns 404 with the canonical
    envelope.
    """
    response = client.delete(
        "/api/v1/tokens/00000000-0000-0000-0000-000000000000",
        headers=human_auth.headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_token_operations_emit_no_audit_rows(
    client: TestClient,
    human_auth: Any,
    session: Session,
) -> None:
    """
    Create + list + revoke leaves ``audit_events`` completely empty.
    This is the load-bearing negative invariant for the tokens service.
    """
    before = session.query(AuditEvent).count()

    created = client.post(
        "/api/v1/tokens",
        json={"actor_type": "human", "actor_id": "adam", "name": "ephemeral"},
        headers=human_auth.headers,
    ).json()
    client.get("/api/v1/tokens", headers=human_auth.headers)
    client.delete(f"/api/v1/tokens/{created['id']}", headers=human_auth.headers)

    assert session.query(AuditEvent).count() == before


def test_list_tokens_hides_revoked_by_default(
    client: TestClient,
    human_auth: Any,
    session: Session,
) -> None:
    """
    By default the list endpoint hides revoked tokens; ``?include_revoked=true``
    returns them.
    """
    created = client.post(
        "/api/v1/tokens",
        json={"actor_type": "human", "actor_id": "adam", "name": "temp"},
        headers=human_auth.headers,
    ).json()
    client.delete(f"/api/v1/tokens/{created['id']}", headers=human_auth.headers)

    default = client.get("/api/v1/tokens", headers=human_auth.headers).json()
    default_ids = {row["id"] for row in default}
    assert created["id"] not in default_ids

    all_rows = client.get(
        "/api/v1/tokens?include_revoked=true", headers=human_auth.headers
    ).json()
    all_ids = {row["id"] for row in all_rows}
    assert created["id"] in all_ids

    assert session.query(ApiToken).count() >= 2  # human_auth token + created
