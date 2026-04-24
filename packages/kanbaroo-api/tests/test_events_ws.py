"""
Integration tests for the ``/api/v1/events`` WebSocket endpoint.

These tests spin up the full FastAPI app through ``TestClient`` and
drive the WebSocket handler end-to-end: they assert the handshake auth
rules, the event fan-out path (REST mutation → bus → socket), and the
keepalive ping schedule.

The keepalive test patches ``EVENT_WS_PING_INTERVAL`` before each
connection so the assertion completes in under two seconds instead of
the production default (30s).
"""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def test_ws_rejects_missing_token(client: TestClient) -> None:
    """
    Opening the socket with no ``token`` query param closes the
    handshake before it is upgraded. ``TestClient`` surfaces the
    rejection as a ``WebSocketDisconnect`` raised on enter.
    """
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/v1/events"),
    ):
        pytest.fail("expected the connection to be rejected")


def test_ws_rejects_invalid_token(client: TestClient) -> None:
    """
    A syntactically-fine but unknown token closes the socket with
    close code 1008 (policy violation).
    """
    with (
        pytest.raises(WebSocketDisconnect) as info,
        client.websocket_connect("/api/v1/events?token=bogus"),
    ):
        pytest.fail("expected the connection to be rejected")
    assert info.value.code == 1008


def test_ws_receives_event_after_rest_mutation(
    client: TestClient, human_auth: Any
) -> None:
    """
    A valid subscription receives the ``workspace.created`` event
    triggered by a REST POST on a separate request.
    """
    token = human_auth.plaintext
    with client.websocket_connect(f"/api/v1/events?token={token}") as ws:
        response = client.post(
            "/api/v1/workspaces",
            json={"key": "KAN", "name": "Kanbaroo"},
            headers=human_auth.headers,
        )
        assert response.status_code == 201
        body = response.json()

        # The server flushes events immediately after commit, but
        # the test event loop may need one scheduler tick to deliver
        # the message. ``receive_json`` blocks until a frame is
        # available, so no manual sleep is required.
        envelope = ws.receive_json()

    assert envelope["event_type"] == "workspace.created"
    assert envelope["entity_type"] == "workspace"
    assert envelope["entity_id"] == body["id"]
    assert envelope["actor_type"] == "human"
    assert envelope["payload"]["key"] == "KAN"


def test_ws_keepalive_ping_shape(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, human_auth: Any
) -> None:
    """
    The server sends a ``{"type": "ping", "ts": ...}`` frame on its
    keepalive schedule. The interval is patched to a fraction of a
    second so this test completes quickly; the patched value is read
    at handshake time via :func:`_resolve_ping_interval`.

    The ping is deliberately NOT shaped like an event envelope, so the
    test asserts the absence of ``event_type`` / ``event_id``.
    """
    monkeypatch.setenv("EVENT_WS_PING_INTERVAL", "0.5")
    token = human_auth.plaintext
    with client.websocket_connect(f"/api/v1/events?token={token}") as ws:
        raw = ws.receive_text()
    frame = json.loads(raw)
    assert frame["type"] == "ping"
    assert isinstance(frame["ts"], str)
    assert "event_type" not in frame
    assert "event_id" not in frame
