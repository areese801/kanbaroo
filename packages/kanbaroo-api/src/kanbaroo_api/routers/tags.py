"""
Tag REST endpoints.

Matches ``docs/spec.md`` section 4.2 for ``/tags``. List and create are
scoped to a workspace path; patch and soft-delete are addressed by tag
id.

Unlike workspaces/epics/stories, tags do **not** carry a ``version``
column in the schema (``docs/spec.md`` section 3.3). Optimistic
concurrency therefore does not apply: PATCH and DELETE here do not
require (and do not consult) ``If-Match``, and no ``ETag`` header is
emitted on tag responses. The surface is intentionally lighter because
tags are effectively immutable metadata from an observer's perspective
once created: the name exists or it does not.

Soft-deleting a tag also detaches it from every story in the same
transaction; the service layer handles that cleanup.
"""

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kanbaroo_api.auth import resolve_actor
from kanbaroo_api.db import get_session
from kanbaroo_core.actor import Actor
from kanbaroo_core.schemas.tag import TagCreate, TagRead, TagUpdate
from kanbaroo_core.services import tags as tag_service

workspace_router = APIRouter(prefix="/workspaces", tags=["tags"])
router = APIRouter(prefix="/tags", tags=["tags"])


class TagListResponse(BaseModel):
    """
    Envelope for tag list responses. No pagination: tag volume per
    workspace is expected to stay well within a single page.
    """

    items: list[TagRead]


@workspace_router.get(
    "/{workspace_id}/tags",
    response_model=TagListResponse,
)
def list_tags(
    workspace_id: str,
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> TagListResponse:
    """
    Return every tag in ``workspace_id``, alphabetised by name.
    """
    rows = tag_service.list_tags(
        session,
        workspace_id=workspace_id,
        include_deleted=include_deleted,
    )
    return TagListResponse(items=[TagRead.model_validate(row) for row in rows])


@workspace_router.get(
    "/{workspace_id}/tags/similar",
    response_model=TagListResponse,
)
def find_similar_tags(
    workspace_id: str,
    name: str = Query(..., description="Tag name to compare against."),
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> TagListResponse:
    """
    Return tags in ``workspace_id`` whose name is normalised
    equivalent to ``name``.

    Used by clients to warn the user before creating a duplicate
    tag with cosmetically different casing or punctuation.
    """
    rows = tag_service.find_similar_tags(
        session,
        workspace_id=workspace_id,
        name=name,
        include_deleted=include_deleted,
    )
    return TagListResponse(items=[TagRead.model_validate(row) for row in rows])


@workspace_router.post(
    "/{workspace_id}/tags",
    response_model=TagRead,
    status_code=status.HTTP_201_CREATED,
)
def create_tag(
    workspace_id: str,
    payload: TagCreate,
    response: Response,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> TagRead:
    """
    Create a workspace-scoped tag. Collisions on ``(workspace_id,
    name)`` return 400 ``validation_error``.
    """
    tag = tag_service.create_tag(
        session,
        actor=actor,
        workspace_id=workspace_id,
        payload=payload,
    )
    response.headers["Location"] = f"/api/v1/tags/{tag.id}"
    return TagRead.model_validate(tag)


@router.patch("/{tag_id}", response_model=TagRead)
def update_tag(
    tag_id: str,
    payload: TagUpdate,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> TagRead:
    """
    Rename or recolour a tag. No ``If-Match`` (tags do not carry a
    version column, per spec §3.3).
    """
    tag = tag_service.update_tag(
        session,
        actor=actor,
        tag_id=tag_id,
        payload=payload,
    )
    return TagRead.model_validate(tag)


@router.delete(
    "/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def soft_delete_tag(
    tag_id: str,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> Response:
    """
    Soft-delete a tag and detach it from every story in the same
    transaction. No ``If-Match`` (tags do not carry a version column,
    per spec §3.3).
    """
    tag_service.soft_delete_tag(
        session,
        actor=actor,
        tag_id=tag_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
