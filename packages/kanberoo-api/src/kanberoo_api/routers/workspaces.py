"""
Workspace REST endpoints.

Matches ``docs/spec.md`` section 4.2 for ``/workspaces``. Every
mutating endpoint requires ``If-Match`` and every response that
carries an entity body also sets ``ETag``. All business logic lives in
:mod:`kanberoo_core.services.workspaces`; these handlers only marshal
HTTP concerns.
"""

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kanberoo_api.auth import resolve_actor
from kanberoo_api.concurrency import etag_for, parse_if_match
from kanberoo_api.db import get_session
from kanberoo_core.actor import Actor
from kanberoo_core.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceUpdate,
)
from kanberoo_core.services import workspaces as ws_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceListResponse(BaseModel):
    """
    Paginated envelope for workspace list responses.

    ``next_cursor`` is ``null`` on the last page. Clients follow the
    cursor until they get back ``null`` to walk the entire collection.
    """

    items: list[WorkspaceRead]
    next_cursor: str | None


@router.get("", response_model=WorkspaceListResponse)
def list_workspaces(
    include_deleted: bool = Query(False),
    cursor: str | None = Query(None),
    limit: int = Query(
        ws_service.DEFAULT_PAGE_LIMIT, ge=1, le=ws_service.MAX_PAGE_LIMIT
    ),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> WorkspaceListResponse:
    """
    Return a page of workspaces plus the next cursor.
    """
    rows, next_cursor = ws_service.list_workspaces(
        session,
        include_deleted=include_deleted,
        cursor=cursor,
        limit=limit,
    )
    return WorkspaceListResponse(
        items=[WorkspaceRead.model_validate(row) for row in rows],
        next_cursor=next_cursor,
    )


@router.post(
    "",
    response_model=WorkspaceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace(
    payload: WorkspaceCreate,
    response: Response,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> WorkspaceRead:
    """
    Create a new workspace and return it with its ETag and Location.
    """
    workspace = ws_service.create_workspace(session, actor=actor, payload=payload)
    response.headers["ETag"] = etag_for(workspace.version)
    response.headers["Location"] = f"/api/v1/workspaces/{workspace.id}"
    return WorkspaceRead.model_validate(workspace)


@router.get("/by-key/{key}", response_model=WorkspaceRead)
def get_workspace_by_key(
    key: str,
    response: Response,
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> WorkspaceRead:
    """
    Return a workspace by its short ``key`` (``KAN``, ``ENG``, ...).

    Mirrors ``GET /stories/by-key`` and ``GET /epics/by-key``: clients
    that know only the human handle can resolve to a full workspace
    without paginating the list surface. Soft-deleted rows 404 unless
    ``include_deleted`` is set.
    """
    workspace = ws_service.get_workspace_by_key(
        session,
        key=key,
        include_deleted=include_deleted,
    )
    response.headers["ETag"] = etag_for(workspace.version)
    return WorkspaceRead.model_validate(workspace)


@router.get("/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(
    workspace_id: str,
    response: Response,
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> WorkspaceRead:
    """
    Return a single workspace. Responds with ``404`` if the id is
    unknown or the row is soft-deleted (unless ``include_deleted`` is
    set).
    """
    workspace = ws_service.get_workspace(
        session,
        workspace_id=workspace_id,
        include_deleted=include_deleted,
    )
    response.headers["ETag"] = etag_for(workspace.version)
    return WorkspaceRead.model_validate(workspace)


@router.patch("/{workspace_id}", response_model=WorkspaceRead)
def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdate,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> WorkspaceRead:
    """
    Patch a workspace. Requires ``If-Match: <version>``; a mismatch
    returns 412.
    """
    expected_version = parse_if_match(request)
    workspace = ws_service.update_workspace(
        session,
        actor=actor,
        workspace_id=workspace_id,
        expected_version=expected_version,
        payload=payload,
    )
    response.headers["ETag"] = etag_for(workspace.version)
    return WorkspaceRead.model_validate(workspace)


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def soft_delete_workspace(
    workspace_id: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> Response:
    """
    Soft-delete a workspace. Requires ``If-Match: <version>``; a
    mismatch returns 412. Soft delete does not cascade.
    """
    expected_version = parse_if_match(request)
    ws_service.soft_delete_workspace(
        session,
        actor=actor,
        workspace_id=workspace_id,
        expected_version=expected_version,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
