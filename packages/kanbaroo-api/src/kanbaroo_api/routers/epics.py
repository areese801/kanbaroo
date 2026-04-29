"""
Epic REST endpoints.

Matches ``docs/spec.md`` section 4.2 for ``/epics``. The list and
create endpoints are scoped to a workspace path; read, update, delete,
and close/reopen are addressed by epic id. Every mutating endpoint
requires ``If-Match``. All business logic lives in
:mod:`kanbaroo_core.services.epics`; these handlers only marshal HTTP
concerns.
"""

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kanbaroo_api.auth import resolve_actor
from kanbaroo_api.concurrency import etag_for, parse_if_match
from kanbaroo_api.db import get_session
from kanbaroo_core.actor import Actor
from kanbaroo_core.schemas.epic import EpicCreate, EpicRead, EpicUpdate
from kanbaroo_core.services import epics as epic_service

workspace_router = APIRouter(prefix="/workspaces", tags=["epics"])
router = APIRouter(prefix="/epics", tags=["epics"])


class EpicListResponse(BaseModel):
    """
    Paginated envelope for epic list responses.
    """

    items: list[EpicRead]
    next_cursor: str | None


@workspace_router.get(
    "/{workspace_id}/epics",
    response_model=EpicListResponse,
)
def list_epics(
    workspace_id: str,
    include_deleted: bool = Query(False),
    cursor: str | None = Query(None),
    limit: int = Query(
        epic_service.DEFAULT_PAGE_LIMIT,
        ge=1,
        le=epic_service.MAX_PAGE_LIMIT,
    ),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> EpicListResponse:
    """
    Return a page of epics belonging to ``workspace_id``.
    """
    rows, next_cursor = epic_service.list_epics(
        session,
        workspace_id=workspace_id,
        include_deleted=include_deleted,
        cursor=cursor,
        limit=limit,
    )
    return EpicListResponse(
        items=[EpicRead.model_validate(row) for row in rows],
        next_cursor=next_cursor,
    )


@workspace_router.get(
    "/{workspace_id}/epics/similar",
    response_model=EpicListResponse,
)
def find_similar_epics(
    workspace_id: str,
    title: str = Query(..., description="Title to compare against."),
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> EpicListResponse:
    """
    Return epics in ``workspace_id`` whose title is normalized
    equivalent to ``title``.

    Mirrors ``GET /workspaces/{id}/stories/similar``; see that
    endpoint's docstring for the normalization rules and intended
    use case (warn-on-create at the client).
    """
    rows = epic_service.find_similar_epics(
        session,
        workspace_id=workspace_id,
        title=title,
        include_deleted=include_deleted,
    )
    return EpicListResponse(
        items=[EpicRead.model_validate(row) for row in rows],
        next_cursor=None,
    )


@workspace_router.post(
    "/{workspace_id}/epics",
    response_model=EpicRead,
    status_code=status.HTTP_201_CREATED,
)
def create_epic(
    workspace_id: str,
    payload: EpicCreate,
    response: Response,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> EpicRead:
    """
    Create a new epic inside ``workspace_id`` and return it with ETag
    and Location headers.
    """
    epic = epic_service.create_epic(
        session,
        actor=actor,
        workspace_id=workspace_id,
        payload=payload,
    )
    response.headers["ETag"] = etag_for(epic.version)
    response.headers["Location"] = f"/api/v1/epics/{epic.id}"
    return EpicRead.model_validate(epic)


@router.get("/by-key/{human_id}", response_model=EpicRead)
def get_epic_by_human_id(
    human_id: str,
    response: Response,
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> EpicRead:
    """
    Return an epic by its ``{KEY}-{N}`` human identifier.

    Mirrors :func:`get_story_by_human_id`; the CLI uses this so that
    the ``--epic KAN-N`` flag can be translated to a UUID without a
    workspace-wide list scan.
    """
    epic = epic_service.get_epic_by_human_id(
        session,
        human_id=human_id,
        include_deleted=include_deleted,
    )
    response.headers["ETag"] = etag_for(epic.version)
    return EpicRead.model_validate(epic)


@router.get("/{epic_id}", response_model=EpicRead)
def get_epic(
    epic_id: str,
    response: Response,
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> EpicRead:
    """
    Return a single epic. Responds with ``404`` if the id is unknown
    or the row is soft-deleted (unless ``include_deleted`` is set).
    """
    epic = epic_service.get_epic(
        session,
        epic_id=epic_id,
        include_deleted=include_deleted,
    )
    response.headers["ETag"] = etag_for(epic.version)
    return EpicRead.model_validate(epic)


@router.patch("/{epic_id}", response_model=EpicRead)
def update_epic(
    epic_id: str,
    payload: EpicUpdate,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> EpicRead:
    """
    Patch an epic. Requires ``If-Match: <version>``; a mismatch
    returns 412.
    """
    expected_version = parse_if_match(request)
    epic = epic_service.update_epic(
        session,
        actor=actor,
        epic_id=epic_id,
        expected_version=expected_version,
        payload=payload,
    )
    response.headers["ETag"] = etag_for(epic.version)
    return EpicRead.model_validate(epic)


@router.delete(
    "/{epic_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def soft_delete_epic(
    epic_id: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> Response:
    """
    Soft-delete an epic. Requires ``If-Match: <version>``; does not
    cascade to the epic's stories.
    """
    expected_version = parse_if_match(request)
    epic_service.soft_delete_epic(
        session,
        actor=actor,
        epic_id=epic_id,
        expected_version=expected_version,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{epic_id}/close", response_model=EpicRead)
def close_epic(
    epic_id: str,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> EpicRead:
    """
    Convenience endpoint that sets the epic's state to ``closed``.
    Idempotent; requires ``If-Match``.
    """
    expected_version = parse_if_match(request)
    epic = epic_service.close_epic(
        session,
        actor=actor,
        epic_id=epic_id,
        expected_version=expected_version,
    )
    response.headers["ETag"] = etag_for(epic.version)
    return EpicRead.model_validate(epic)


@router.post("/{epic_id}/reopen", response_model=EpicRead)
def reopen_epic(
    epic_id: str,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> EpicRead:
    """
    Convenience endpoint that sets the epic's state to ``open``.
    Idempotent; requires ``If-Match``.
    """
    expected_version = parse_if_match(request)
    epic = epic_service.reopen_epic(
        session,
        actor=actor,
        epic_id=epic_id,
        expected_version=expected_version,
    )
    response.headers["ETag"] = etag_for(epic.version)
    return EpicRead.model_validate(epic)
