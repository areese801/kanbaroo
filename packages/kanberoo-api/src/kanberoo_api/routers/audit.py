"""
Audit REST endpoints (spec section 4.2).

Two shapes:

* ``GET /api/v1/audit`` -global feed with optional filters on
  entity_type, entity_id, actor_type, actor_id, and since; paginated
  newest-first with an opaque cursor.
* ``GET /api/v1/audit/entity/{entity_type}/{entity_id}`` -convenience
  path for a single entity's history. Clients and MCP tools that
  already know the ``(type, id)`` pair prefer this because it is the
  path segment already wired up in the TUI story detail screen and
  the MCP ``get_audit_trail`` tool.

Audit events are never mutated, so neither endpoint touches ETag or
``If-Match`` and neither emits an audit row of its own. All business
logic lives in :mod:`kanberoo_core.services.audit`.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from kanberoo_api.auth import resolve_actor
from kanberoo_api.db import get_session
from kanberoo_core.actor import Actor
from kanberoo_core.enums import ActorType, AuditEntityType
from kanberoo_core.schemas.audit import AuditEventRead
from kanberoo_core.services import audit as audit_service

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditListResponse(BaseModel):
    """
    Paginated envelope for audit listing responses.

    Matches the shape used by every other list endpoint so clients can
    reuse the cursor-pagination helper they already have.
    """

    items: list[AuditEventRead]
    next_cursor: str | None


@router.get("", response_model=AuditListResponse)
def list_audit(
    entity_type: AuditEntityType | None = Query(None),
    entity_id: str | None = Query(None),
    actor_type: ActorType | None = Query(None),
    actor_id: str | None = Query(None),
    since: str | None = Query(None),
    cursor: str | None = Query(None),
    limit: int = Query(
        audit_service.DEFAULT_AUDIT_LIMIT,
        ge=1,
        le=audit_service.MAX_AUDIT_LIMIT,
    ),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> AuditListResponse:
    """
    Return a newest-first page of audit events with filters applied.
    """
    rows, next_cursor = audit_service.list_audit(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_type=actor_type,
        actor_id=actor_id,
        since=since,
        cursor=cursor,
        limit=limit,
    )
    return AuditListResponse(
        items=[AuditEventRead.model_validate(row) for row in rows],
        next_cursor=next_cursor,
    )


@router.get(
    "/entity/{entity_type}/{entity_id}",
    response_model=AuditListResponse,
)
def list_audit_for_entity(
    entity_type: AuditEntityType,
    entity_id: str,
    cursor: str | None = Query(None),
    limit: int = Query(
        audit_service.DEFAULT_AUDIT_LIMIT,
        ge=1,
        le=audit_service.MAX_AUDIT_LIMIT,
    ),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> AuditListResponse:
    """
    Return a newest-first page of audit events for a single entity.
    """
    rows, next_cursor = audit_service.list_audit_for_entity(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        cursor=cursor,
        limit=limit,
    )
    return AuditListResponse(
        items=[AuditEventRead.model_validate(row) for row in rows],
        next_cursor=next_cursor,
    )
