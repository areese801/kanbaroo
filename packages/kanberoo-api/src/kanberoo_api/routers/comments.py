"""
Comment REST endpoints.

Matches ``docs/spec.md`` section 4.2 for ``/comments``. List and create
are scoped to a story path; read, update, and soft-delete are addressed
by comment id. Every mutating endpoint requires ``If-Match``. All
business logic lives in :mod:`kanberoo_core.services.comments`; these
handlers only marshal HTTP concerns.
"""

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kanberoo_api.auth import resolve_actor
from kanberoo_api.concurrency import etag_for, parse_if_match
from kanberoo_api.db import get_session
from kanberoo_core.actor import Actor
from kanberoo_core.schemas.comment import CommentCreate, CommentRead, CommentUpdate
from kanberoo_core.services import comments as comment_service

story_router = APIRouter(prefix="/stories", tags=["comments"])
router = APIRouter(prefix="/comments", tags=["comments"])


class CommentListResponse(BaseModel):
    """
    Envelope for comment list responses. No pagination in this
    milestone: the flat list is expected to stay small per story.
    """

    items: list[CommentRead]


@story_router.get(
    "/{story_id}/comments",
    response_model=CommentListResponse,
)
def list_comments(
    story_id: str,
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> CommentListResponse:
    """
    Return every comment on ``story_id`` chronologically.
    """
    rows = comment_service.list_comments(
        session,
        story_id=story_id,
        include_deleted=include_deleted,
    )
    return CommentListResponse(
        items=[CommentRead.model_validate(row) for row in rows],
    )


@story_router.post(
    "/{story_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    story_id: str,
    payload: CommentCreate,
    response: Response,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> CommentRead:
    """
    Create a new comment on ``story_id`` and return it with ETag and
    Location headers. Threading is limited to one level; replies to
    replies are rejected with ``400 validation_error``.
    """
    comment = comment_service.create_comment(
        session,
        actor=actor,
        story_id=story_id,
        payload=payload,
    )
    response.headers["ETag"] = etag_for(comment.version)
    response.headers["Location"] = f"/api/v1/comments/{comment.id}"
    return CommentRead.model_validate(comment)


@router.get("/{comment_id}", response_model=CommentRead)
def get_comment(
    comment_id: str,
    response: Response,
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> CommentRead:
    """
    Return a single comment. Responds with ``404`` if the id is
    unknown or soft-deleted (unless ``include_deleted`` is set).
    """
    comment = comment_service.get_comment(
        session,
        comment_id=comment_id,
        include_deleted=include_deleted,
    )
    response.headers["ETag"] = etag_for(comment.version)
    return CommentRead.model_validate(comment)


@router.patch("/{comment_id}", response_model=CommentRead)
def update_comment(
    comment_id: str,
    payload: CommentUpdate,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> CommentRead:
    """
    Patch a comment's body. Requires ``If-Match: <version>``; a
    mismatch returns 412. ``parent_id`` is intentionally not patchable.
    """
    expected_version = parse_if_match(request)
    comment = comment_service.update_comment(
        session,
        actor=actor,
        comment_id=comment_id,
        expected_version=expected_version,
        payload=payload,
    )
    response.headers["ETag"] = etag_for(comment.version)
    return CommentRead.model_validate(comment)


@router.delete(
    "/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def soft_delete_comment(
    comment_id: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> Response:
    """
    Soft-delete a comment. Requires ``If-Match: <version>``. Does not
    cascade to replies.
    """
    expected_version = parse_if_match(request)
    comment_service.soft_delete_comment(
        session,
        actor=actor,
        comment_id=comment_id,
        expected_version=expected_version,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
