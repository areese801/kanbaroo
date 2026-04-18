"""
Workspace export endpoint (spec milestone 16).

``GET /api/v1/workspaces/{workspace_id}/export`` streams a tarball
containing Parquet per table, a self-contained SQLite copy, and a
schema-version manifest. The build happens in memory in
:func:`kanberoo_core.services.export.export_workspace`; this router
wraps it in a streaming response with a download-friendly filename.

Export is a read operation and therefore emits no audit row; the
underlying service does not call the audit path either.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from kanberoo_api.auth import resolve_actor
from kanberoo_api.db import get_session
from kanberoo_core.actor import Actor
from kanberoo_core.services import export as export_service
from kanberoo_core.services import workspaces as ws_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("/{workspace_id}/export")
def export_workspace(
    workspace_id: str,
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> StreamingResponse:
    """
    Stream the workspace's full export archive back to the caller.

    The archive is built in memory before the first byte ships so the
    response can carry a ``Content-Length`` header (also lets the
    service layer raise a clean 404 before a partial body is sent).
    """
    workspace = ws_service.get_workspace(
        session,
        workspace_id=workspace_id,
        include_deleted=include_deleted,
    )
    archive = export_service.export_workspace(
        session,
        workspace_id=workspace_id,
        include_deleted=include_deleted,
    )
    filename = export_service.export_filename_for(workspace.key)

    def _stream() -> "list[bytes]":
        """
        Wrap the bytes buffer as a single-chunk iterable for
        :class:`StreamingResponse`; the whole archive is already
        materialised, so chunked IO is unnecessary.
        """
        return [archive]

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(len(archive)),
    }
    return StreamingResponse(
        _stream(),
        media_type="application/gzip",
        headers=headers,
    )
