"""
Story REST endpoints.

Matches ``docs/spec.md`` section 4.2 for ``/stories``. The list and
create endpoints are scoped to a workspace path; read, update, delete,
by-key lookup, and the transition endpoint are addressed by story id
(or human id for by-key). Every mutating endpoint requires
``If-Match``. All business logic lives in
:mod:`kanbaroo_core.services.stories`; these handlers only marshal HTTP
concerns.
"""

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kanbaroo_api.auth import resolve_actor
from kanbaroo_api.concurrency import etag_for, parse_if_match
from kanbaroo_api.db import get_session
from kanbaroo_api.routers.tags import TagListResponse
from kanbaroo_core.actor import Actor
from kanbaroo_core.enums import StoryPriority, StoryState
from kanbaroo_core.schemas.story import (
    StoryCreate,
    StoryRead,
    StoryTransitionRequest,
    StoryUpdate,
)
from kanbaroo_core.schemas.tag import TagRead
from kanbaroo_core.services import stories as story_service
from kanbaroo_core.services import tags as tag_service

workspace_router = APIRouter(prefix="/workspaces", tags=["stories"])
router = APIRouter(prefix="/stories", tags=["stories"])


class StoryListResponse(BaseModel):
    """
    Paginated envelope for story list responses.
    """

    items: list[StoryRead]
    next_cursor: str | None


class StoryTagAddRequest(BaseModel):
    """
    Payload for ``POST /stories/{id}/tags``.
    """

    tag_ids: list[str]


@workspace_router.get(
    "/{workspace_id}/stories",
    response_model=StoryListResponse,
)
def list_stories(
    workspace_id: str,
    state: StoryState | None = Query(None),
    priority: StoryPriority | None = Query(None),
    epic_id: str | None = Query(None),
    tag: str | None = Query(None),
    include_deleted: bool = Query(False),
    cursor: str | None = Query(None),
    limit: int = Query(
        story_service.DEFAULT_PAGE_LIMIT,
        ge=1,
        le=story_service.MAX_PAGE_LIMIT,
    ),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> StoryListResponse:
    """
    Return a page of stories in ``workspace_id`` with optional filters.
    """
    rows, next_cursor = story_service.list_stories(
        session,
        workspace_id=workspace_id,
        state=state,
        priority=priority,
        epic_id=epic_id,
        tag=tag,
        include_deleted=include_deleted,
        cursor=cursor,
        limit=limit,
    )
    return StoryListResponse(
        items=[StoryRead.model_validate(row) for row in rows],
        next_cursor=next_cursor,
    )


@workspace_router.get(
    "/{workspace_id}/stories/similar",
    response_model=StoryListResponse,
)
def find_similar_stories(
    workspace_id: str,
    title: str = Query(..., description="Title to compare against."),
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> StoryListResponse:
    """
    Return stories in ``workspace_id`` whose title is normalised
    equivalent to ``title`` (see
    :func:`kanbaroo_core.text.normalize_for_comparison`).

    Used by clients to warn the user before creating a duplicate.
    The response envelope reuses :class:`StoryListResponse` for shape
    consistency; ``next_cursor`` is always ``null`` because the
    result set is intentionally unpaginated.
    """
    rows = story_service.find_similar_stories(
        session,
        workspace_id=workspace_id,
        title=title,
        include_deleted=include_deleted,
    )
    return StoryListResponse(
        items=[StoryRead.model_validate(row) for row in rows],
        next_cursor=None,
    )


@workspace_router.post(
    "/{workspace_id}/stories",
    response_model=StoryRead,
    status_code=status.HTTP_201_CREATED,
)
def create_story(
    workspace_id: str,
    payload: StoryCreate,
    response: Response,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> StoryRead:
    """
    Create a new story in ``workspace_id`` and return it with ETag and
    Location headers.
    """
    story = story_service.create_story(
        session,
        actor=actor,
        workspace_id=workspace_id,
        payload=payload,
    )
    response.headers["ETag"] = etag_for(story.version)
    response.headers["Location"] = f"/api/v1/stories/{story.id}"
    return StoryRead.model_validate(story)


@router.get("/by-key/{human_id}", response_model=StoryRead)
def get_story_by_human_id(
    human_id: str,
    response: Response,
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> StoryRead:
    """
    Return a story by its ``{KEY}-{N}`` human identifier.
    """
    story = story_service.get_story_by_human_id(
        session,
        human_id=human_id,
        include_deleted=include_deleted,
    )
    response.headers["ETag"] = etag_for(story.version)
    return StoryRead.model_validate(story)


@router.get("/{story_id}", response_model=StoryRead)
def get_story(
    story_id: str,
    response: Response,
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> StoryRead:
    """
    Return a single story. Responds with ``404`` if the id is unknown
    or the row is soft-deleted (unless ``include_deleted`` is set).
    """
    story = story_service.get_story(
        session,
        story_id=story_id,
        include_deleted=include_deleted,
    )
    response.headers["ETag"] = etag_for(story.version)
    return StoryRead.model_validate(story)


@router.patch("/{story_id}", response_model=StoryRead)
def update_story(
    story_id: str,
    payload: StoryUpdate,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> StoryRead:
    """
    Patch a story. Requires ``If-Match: <version>``; a mismatch returns
    412. State transitions go through the dedicated transition
    endpoint, not this one.
    """
    expected_version = parse_if_match(request)
    story = story_service.update_story(
        session,
        actor=actor,
        story_id=story_id,
        expected_version=expected_version,
        payload=payload,
    )
    response.headers["ETag"] = etag_for(story.version)
    return StoryRead.model_validate(story)


@router.delete(
    "/{story_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def soft_delete_story(
    story_id: str,
    request: Request,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> Response:
    """
    Soft-delete a story. Requires ``If-Match: <version>``.
    """
    expected_version = parse_if_match(request)
    story_service.soft_delete_story(
        session,
        actor=actor,
        story_id=story_id,
        expected_version=expected_version,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{story_id}/tags",
    response_model=TagListResponse,
)
def list_tags_for_story(
    story_id: str,
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> TagListResponse:
    """
    Return every live tag currently associated with ``story_id``,
    alphabetised by name. 404 if the story is missing or soft-deleted.

    Not paginated: in practice a single story carries a small, bounded
    set of tags. No ``If-Match`` or ``ETag`` (tags do not carry a
    version, per spec 3.3).
    """
    rows = tag_service.list_tags_for_story(session, story_id=story_id)
    return TagListResponse(items=[TagRead.model_validate(row) for row in rows])


@router.post(
    "/{story_id}/tags",
    response_model=StoryRead,
)
def add_tags_to_story(
    story_id: str,
    payload: StoryTagAddRequest,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> StoryRead:
    """
    Associate tags with a story. Idempotent: already-associated tags
    are silently skipped. Cross-workspace tagging returns 400
    ``validation_error``. No ``If-Match`` required (association is
    orthogonal to story version).
    """
    story = tag_service.add_tags_to_story(
        session,
        actor=actor,
        story_id=story_id,
        tag_ids=payload.tag_ids,
    )
    return StoryRead.model_validate(story)


@router.delete(
    "/{story_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def remove_tag_from_story(
    story_id: str,
    tag_id: str,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> Response:
    """
    Remove a tag from a story. Idempotent: removing a non-associated
    tag is a no-op and does not emit an audit row. No ``If-Match``
    required.
    """
    tag_service.remove_tag_from_story(
        session,
        actor=actor,
        story_id=story_id,
        tag_id=tag_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{story_id}/transition", response_model=StoryRead)
def transition_story(
    story_id: str,
    payload: StoryTransitionRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> StoryRead:
    """
    Move a story to a new state, enforcing the state machine defined
    in ``docs/spec.md`` section 4.3. Requires ``If-Match``.
    """
    expected_version = parse_if_match(request)
    story = story_service.transition_story(
        session,
        actor=actor,
        story_id=story_id,
        expected_version=expected_version,
        to_state=payload.to_state,
        reason=payload.reason,
    )
    response.headers["ETag"] = etag_for(story.version)
    return StoryRead.model_validate(story)
