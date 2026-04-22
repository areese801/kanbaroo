"""
Tests for the optional ``/ui`` static mount.

These tests run only when ``kanberoo-web`` is installed (the standard dev
workspace installs it via ``uv sync --all-packages --dev``). They verify
that the mount serves ``index.html`` at the root, falls back to it for
unknown deep paths (SPA routing), and does not shadow the REST surface
at ``/api/v1``.
"""

from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

kanberoo_web = pytest.importorskip("kanberoo_web")


def test_ui_root_returns_placeholder(client: TestClient) -> None:
    """
    ``GET /ui/`` serves the placeholder ``index.html`` with a 200.
    """
    response = client.get("/ui/")
    assert response.status_code == 200
    assert "Kanberoo" in response.text


def test_ui_deep_route_falls_back_to_index(client: TestClient) -> None:
    """
    Deep client-side routes that do not match a real file fall back to
    ``index.html`` so the SPA router can render them.
    """
    response = client.get("/ui/board/KAN-1")
    assert response.status_code == 200
    assert "Kanberoo" in response.text


def test_api_routes_still_work(client: TestClient, human_auth: Any) -> None:
    """
    Mounting ``/ui`` must not interfere with existing ``/api/v1`` routes.
    """
    response = client.get("/api/v1/workspaces", headers=human_auth.headers)
    assert response.status_code == 200
    body = response.json()
    assert "items" in body


def test_ui_rejects_path_traversal(client: TestClient) -> None:
    """
    Encoded path-traversal attempts on ``/ui/`` must not serve files
    from outside the bundled assets directory. The handler resolves the
    candidate path, verifies containment under the assets root, and
    falls back to ``index.html`` when the resolved path escapes. The
    attempted path is never echoed back in the response.
    """
    etc_passwd_payload = quote("../" * 12 + "etc/passwd", safe="")
    response = client.get(f"/ui/{etc_passwd_payload}")
    assert response.status_code == 200
    assert "Kanberoo" in response.text
    assert "root:" not in response.text
    assert "/bin/" not in response.text

    pyproject_payload = quote("../" * 6 + "pyproject.toml", safe="")
    response = client.get(f"/ui/{pyproject_payload}")
    assert response.status_code == 200
    assert "Kanberoo" in response.text
    assert "[project]" not in response.text
    assert "[tool." not in response.text


def test_web_assets_path_points_at_bundled_dist() -> None:
    """
    ``web_assets_path()`` returns a directory that contains ``index.html``.
    """
    assets = kanberoo_web.web_assets_path()
    assert assets.is_dir()
    assert (assets / "index.html").is_file()
