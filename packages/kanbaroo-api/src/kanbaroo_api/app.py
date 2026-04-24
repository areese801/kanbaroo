"""
FastAPI application factory.

:func:`create_app` builds a fully-wired app: engine, session
dependency, exception handlers, and routers mounted under
``/api/v1``. The factory is the single public entry point for both the
uvicorn server and the test suite so the two paths cannot drift.

When the optional ``kanbaroo-web`` package is installed (via the
``kanbaroo-api[web]`` extra) the app also serves the bundled web UI at
``/ui`` with an SPA fallback. If the package is not installed the route
is silently skipped and the API still serves normally.
"""

import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from kanbaroo_api.db import configure_engine
from kanbaroo_api.errors import register_exception_handlers
from kanbaroo_api.routers import audit as audit_router
from kanbaroo_api.routers import comments as comments_router
from kanbaroo_api.routers import epics as epics_router
from kanbaroo_api.routers import events_ws as events_ws_router
from kanbaroo_api.routers import export as export_router
from kanbaroo_api.routers import linkages as linkages_router
from kanbaroo_api.routers import stories as stories_router
from kanbaroo_api.routers import tags as tags_router
from kanbaroo_api.routers import tokens as tokens_router
from kanbaroo_api.routers import workspaces as workspaces_router

try:
    from kanbaroo_web import web_assets_path as _web_assets_path
except ImportError:
    _web_assets_path = None  # type: ignore[assignment]

API_PREFIX = "/api/v1"
UI_PREFIX = "/ui"


def create_app(*, database_url: str | None = None) -> FastAPI:
    """
    Build a configured FastAPI application.

    ``database_url`` defaults to ``$KANBAROO_DATABASE_URL``. If neither
    is set a :class:`RuntimeError` is raised so misconfiguration is
    caught at startup rather than on the first request. Tests pass an
    explicit URL (usually ``sqlite:///:memory:``) and do **not**
    depend on environment state.
    """
    resolved_url = database_url or os.environ.get("KANBAROO_DATABASE_URL")
    if not resolved_url:
        raise RuntimeError(
            "KANBAROO_DATABASE_URL is not set and no database_url was passed "
            "to create_app()."
        )

    app = FastAPI(
        title="Kanbaroo API",
        version="0.1.0",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=f"{API_PREFIX}/redoc",
    )
    configure_engine(app.state, resolved_url)
    register_exception_handlers(app)

    app.include_router(export_router.router, prefix=API_PREFIX)
    app.include_router(workspaces_router.router, prefix=API_PREFIX)
    app.include_router(audit_router.router, prefix=API_PREFIX)
    app.include_router(epics_router.workspace_router, prefix=API_PREFIX)
    app.include_router(epics_router.router, prefix=API_PREFIX)
    app.include_router(stories_router.workspace_router, prefix=API_PREFIX)
    app.include_router(stories_router.router, prefix=API_PREFIX)
    app.include_router(comments_router.story_router, prefix=API_PREFIX)
    app.include_router(comments_router.router, prefix=API_PREFIX)
    app.include_router(tags_router.workspace_router, prefix=API_PREFIX)
    app.include_router(tags_router.router, prefix=API_PREFIX)
    app.include_router(linkages_router.story_router, prefix=API_PREFIX)
    app.include_router(linkages_router.router, prefix=API_PREFIX)
    app.include_router(tokens_router.router, prefix=API_PREFIX)
    app.include_router(events_ws_router.router, prefix=API_PREFIX)

    if _web_assets_path is not None:
        _mount_web_ui(app)

    return app


def _mount_web_ui(app: FastAPI) -> None:
    """
    Register the ``/ui`` catch-all that serves the kanbaroo-web bundle.

    A single ``GET /ui/{path:path}`` handler resolves the requested path
    against the bundled assets directory and returns the file when one
    exists. Requests whose resolved path escapes the assets directory
    (path traversal) are treated as unknown routes and fall back to
    ``index.html`` so the SPA router can render them; the attempted path
    is not echoed back. Any unmatched in-bounds path also falls back to
    ``index.html`` for the same reason.
    """
    assert _web_assets_path is not None
    assets_dir = _web_assets_path()
    root = assets_dir.resolve()
    index_html = root / "index.html"

    @app.get(f"{UI_PREFIX}/{{path:path}}", include_in_schema=False)
    async def web_ui(path: str) -> FileResponse:
        if path:
            resolved = (assets_dir / path).resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                resolved = index_html
            if resolved != index_html and resolved.is_file():
                return FileResponse(resolved)
        if index_html.is_file():
            return FileResponse(index_html)
        raise HTTPException(status_code=404, detail="web assets not found")
