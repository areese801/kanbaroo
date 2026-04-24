"""
Linkage REST endpoints.

Matches ``docs/spec.md`` section 4.2 for ``/linkages``. Linkages do not
carry a ``version`` column (spec §3.3), so create and delete do not
require ``If-Match`` and no ``ETag`` header is emitted on linkage
responses.

``GET /stories/{id}/linkages`` returns the union of incoming and
outgoing linkages; callers distinguish the directions by comparing
``source_id``/``target_id`` against the queried story id.
"""

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kanbaroo_api.auth import resolve_actor
from kanbaroo_api.db import get_session
from kanbaroo_core.actor import Actor
from kanbaroo_core.schemas.linkage import LinkageCreate, LinkageRead
from kanbaroo_core.services import linkages as linkage_service

story_router = APIRouter(prefix="/stories", tags=["linkages"])
router = APIRouter(prefix="/linkages", tags=["linkages"])


class LinkageListResponse(BaseModel):
    """
    Envelope for linkage list responses. No pagination in this
    milestone.
    """

    items: list[LinkageRead]


@story_router.get(
    "/{story_id}/linkages",
    response_model=LinkageListResponse,
)
def list_story_linkages(
    story_id: str,
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> LinkageListResponse:
    """
    Return every linkage touching ``story_id`` (as source or target),
    ordered by creation time.
    """
    rows = linkage_service.list_linkages_for_story(
        session,
        story_id=story_id,
        include_deleted=include_deleted,
    )
    return LinkageListResponse(
        items=[LinkageRead.model_validate(row) for row in rows],
    )


@router.post(
    "",
    response_model=LinkageRead,
    status_code=status.HTTP_201_CREATED,
)
def create_linkage(
    payload: LinkageCreate,
    response: Response,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> LinkageRead:
    """
    Create a linkage. ``blocks`` / ``is_blocked_by`` pairs are
    auto-mirrored on the other endpoint; other link types are
    unidirectional.
    """
    linkage = linkage_service.create_linkage(
        session,
        actor=actor,
        payload=payload,
    )
    response.headers["Location"] = f"/api/v1/linkages/{linkage.id}"
    return LinkageRead.model_validate(linkage)


@router.delete(
    "/{linkage_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_linkage(
    linkage_id: str,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> Response:
    """
    Soft-delete a linkage. The mirror end is soft-deleted in the same
    transaction for blocking pairs. No ``If-Match`` required.
    """
    linkage_service.delete_linkage(
        session,
        actor=actor,
        linkage_id=linkage_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
