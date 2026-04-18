"""
FastAPI application factory.

:func:`create_app` builds a fully-wired app: engine, session
dependency, exception handlers, and routers mounted under
``/api/v1``. The factory is the single public entry point for both the
uvicorn server and the test suite so the two paths cannot drift.
"""

import os

from fastapi import FastAPI

from kanberoo_api.db import configure_engine
from kanberoo_api.errors import register_exception_handlers
from kanberoo_api.routers import audit as audit_router
from kanberoo_api.routers import comments as comments_router
from kanberoo_api.routers import epics as epics_router
from kanberoo_api.routers import events_ws as events_ws_router
from kanberoo_api.routers import export as export_router
from kanberoo_api.routers import linkages as linkages_router
from kanberoo_api.routers import stories as stories_router
from kanberoo_api.routers import tags as tags_router
from kanberoo_api.routers import tokens as tokens_router
from kanberoo_api.routers import workspaces as workspaces_router

API_PREFIX = "/api/v1"


def create_app(*, database_url: str | None = None) -> FastAPI:
    """
    Build a configured FastAPI application.

    ``database_url`` defaults to ``$KANBEROO_DATABASE_URL``. If neither
    is set a :class:`RuntimeError` is raised so misconfiguration is
    caught at startup rather than on the first request. Tests pass an
    explicit URL (usually ``sqlite:///:memory:``) and do **not**
    depend on environment state.
    """
    resolved_url = database_url or os.environ.get("KANBEROO_DATABASE_URL")
    if not resolved_url:
        raise RuntimeError(
            "KANBEROO_DATABASE_URL is not set and no database_url was passed "
            "to create_app()."
        )

    app = FastAPI(
        title="Kanberoo API",
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

    return app
