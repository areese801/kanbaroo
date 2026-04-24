"""
Tests for the canonical error shape.

The wire contract from ``docs/spec.md`` section 4.1 says every non-2xx
body is ``{"error": {"code", "message", "details"}}``. These tests
exercise the handler registration across 400/401/404/412/500 and make
sure the shape is stable.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kanbaroo_api.errors import build_error_response


def test_missing_auth_has_canonical_shape(client: TestClient) -> None:
    """
    401 responses follow the canonical shape.
    """
    body = client.get("/api/v1/workspaces").json()
    assert set(body["error"].keys()) == {"code", "message", "details"}
    assert body["error"]["code"] == "unauthorized"


def test_unknown_workspace_has_canonical_shape(
    client: TestClient, human_auth: Any
) -> None:
    """
    404 responses follow the canonical shape and carry the entity id in
    details.
    """
    response = client.get(
        "/api/v1/workspaces/does-not-exist", headers=human_auth.headers
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["details"]["entity_id"] == "does-not-exist"


def test_invalid_request_body_is_400(client: TestClient, human_auth: Any) -> None:
    """
    A request body that fails Pydantic validation returns 400 with the
    canonical envelope, not FastAPI's default ``{"detail": [...]}``.
    """
    response = client.post(
        "/api/v1/workspaces",
        json={"key": "KAN"},  # Missing "name"
        headers=human_auth.headers,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert "errors" in body["error"]["details"]


def test_malformed_if_match_is_400(client: TestClient, human_auth: Any) -> None:
    """
    A non-integer ``If-Match`` returns 400 with the canonical envelope.
    """
    created = client.post(
        "/api/v1/workspaces",
        json={"key": "KAN", "name": "Kanbaroo"},
        headers=human_auth.headers,
    ).json()
    response = client.patch(
        f"/api/v1/workspaces/{created['id']}",
        json={"name": "x"},
        headers={**human_auth.headers, "If-Match": "not-an-int"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_if_match"


def test_unexpected_exception_returns_500() -> None:
    """
    Uncaught exceptions funnel through the fallback handler and return
    the canonical envelope with ``code=internal_error``.

    Uses a separate FastAPI app plus a trivially-broken route rather
    than pokeing the real app, so the test does not depend on bugs in
    the product code.
    """
    from kanbaroo_api.errors import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def _boom() -> dict[str, str]:
        raise RuntimeError("pretend failure")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"


def test_build_error_response_emits_json_body() -> None:
    """
    The builder helper produces the documented shape without needing a
    request context.
    """
    import json

    response = build_error_response(
        status_code=418,
        code="teapot",
        message="I'm a teapot",
        details={"hint": "short and stout"},
    )
    payload = json.loads(bytes(response.body).decode())
    assert payload == {
        "error": {
            "code": "teapot",
            "message": "I'm a teapot",
            "details": {"hint": "short and stout"},
        }
    }


@pytest.mark.parametrize(
    "status_code,expected_code",
    [(401, "unauthorized"), (403, "forbidden"), (404, "not_found")],
)
def test_default_code_mapping(status_code: int, expected_code: str) -> None:
    """
    The default-code helper picks sensible identifiers per status.
    """
    from kanbaroo_api.errors import _default_code_for_status

    assert _default_code_for_status(status_code) == expected_code
