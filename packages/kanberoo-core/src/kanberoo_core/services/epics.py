"""
Epic CRUD service.

Epics are optional containers grouping related stories within a
workspace. As with workspaces, every mutation flows through this module
so audit emission cannot be bypassed: endpoints call service functions,
and service functions call :func:`emit_audit` within the same
transaction.

Per ``docs/spec.md`` section 3.4 epics and stories share the workspace's
``next_issue_num`` counter, so a given human ID (``KAN-7``) uniquely
identifies either an epic or a story, never both.

Soft deletes do not cascade to the epic's stories. The stories retain
their ``epic_id`` pointer to the deleted epic; the epic is simply
hidden from the default list and read paths.
"""

import base64
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kanberoo_core.actor import Actor
from kanberoo_core.enums import AuditAction, AuditEntityType, EpicState
from kanberoo_core.id_generator import generate_human_id
from kanberoo_core.models.epic import Epic
from kanberoo_core.queries import live
from kanberoo_core.schemas.epic import EpicCreate, EpicRead, EpicUpdate
from kanberoo_core.services.audit import emit_audit
from kanberoo_core.services.events import publish_event
from kanberoo_core.services.exceptions import (
    NotFoundError,
    ValidationError,
    VersionConflictError,
)
from kanberoo_core.time import utc_now_iso

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200


def _dump(epic: Epic) -> dict[str, Any]:
    """
    Serialise an :class:`Epic` row into a JSON-friendly dict for the
    audit log.
    """
    return EpicRead.model_validate(epic).model_dump(mode="json")


def _encode_cursor(epic_id: str) -> str:
    """
    Encode an epic id as an opaque URL-safe cursor.
    """
    return base64.urlsafe_b64encode(epic_id.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> str:
    """
    Decode a cursor back into the epic id it wraps.

    Raises :class:`ValidationError` if the cursor is not valid base64
    URL-safe data; this translates to a 400 at the API layer.
    """
    try:
        return base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("cursor", "malformed cursor value") from exc


def create_epic(
    session: Session,
    *,
    actor: Actor,
    workspace_id: str,
    payload: EpicCreate,
) -> Epic:
    """
    Create a new epic and emit an audit event.

    Allocates the next ``{KEY}-{N}`` human identifier from the
    workspace's shared counter; see
    :func:`kanberoo_core.id_generator.generate_human_id`. Raises
    :class:`NotFoundError` if the workspace does not exist.
    """
    try:
        human_id = generate_human_id(session, workspace_id)
    except ValueError as exc:
        raise NotFoundError("workspace", workspace_id) from exc

    epic = Epic(
        workspace_id=workspace_id,
        human_id=human_id,
        title=payload.title,
        description=payload.description,
    )
    session.add(epic)
    session.flush()

    after = _dump(epic)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.EPIC,
        entity_id=epic.id,
        action=AuditAction.CREATED,
        before=None,
        after=after,
    )
    publish_event(
        session,
        event_type="epic.created",
        actor=actor,
        entity_type=AuditEntityType.EPIC.value,
        entity_id=epic.id,
        entity_version=epic.version,
        payload=after,
    )
    return epic


def list_epics(
    session: Session,
    *,
    workspace_id: str,
    include_deleted: bool = False,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> tuple[list[Epic], str | None]:
    """
    Return a page of epics in a workspace plus a cursor for the next
    page.

    Ordering is by ``id`` (UUID v7: time-sortable). ``limit`` is clamped
    to the inclusive range ``[1, MAX_PAGE_LIMIT]``.
    """
    if limit < 1:
        limit = 1
    if limit > MAX_PAGE_LIMIT:
        limit = MAX_PAGE_LIMIT

    stmt = select(Epic).where(Epic.workspace_id == workspace_id).order_by(Epic.id)
    if not include_deleted:
        stmt = live(stmt, Epic)
    if cursor is not None:
        stmt = stmt.where(Epic.id > _decode_cursor(cursor))
    stmt = stmt.limit(limit + 1)

    rows = list(session.execute(stmt).scalars().all())
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1].id)
    return rows, next_cursor


def get_epic(
    session: Session,
    *,
    epic_id: str,
    include_deleted: bool = False,
) -> Epic:
    """
    Return an epic by id or raise :class:`NotFoundError`.

    By default soft-deleted rows are treated as missing. Callers that
    need to read an archived epic (admin tools, audit views) pass
    ``include_deleted=True``.
    """
    epic = session.get(Epic, epic_id)
    if epic is None:
        raise NotFoundError("epic", epic_id)
    if epic.deleted_at is not None and not include_deleted:
        raise NotFoundError("epic", epic_id)
    return epic


def get_epic_by_human_id(
    session: Session,
    *,
    human_id: str,
    include_deleted: bool = False,
) -> Epic:
    """
    Return an epic by its ``{KEY}-{N}`` human identifier or raise
    :class:`NotFoundError`.

    Used by the ``GET /epics/by-key/{human_id}`` endpoint. Soft-
    deleted rows are hidden unless ``include_deleted`` is ``True``.
    """
    stmt = select(Epic).where(Epic.human_id == human_id)
    epic = session.execute(stmt).scalar_one_or_none()
    if epic is None:
        raise NotFoundError("epic", human_id)
    if epic.deleted_at is not None and not include_deleted:
        raise NotFoundError("epic", human_id)
    return epic


def update_epic(
    session: Session,
    *,
    actor: Actor,
    epic_id: str,
    expected_version: int,
    payload: EpicUpdate,
) -> Epic:
    """
    Apply a ``PATCH`` payload to an epic.

    Enforces optimistic concurrency: the caller supplies the ``version``
    they read, and a mismatch raises :class:`VersionConflictError`.
    Only fields explicitly set in ``payload`` are updated. The epic's
    workspace is not patchable (the schema does not expose it), so
    cross-workspace moves are not possible here.
    """
    epic = get_epic(session, epic_id=epic_id)
    if epic.version != expected_version:
        raise VersionConflictError(
            "epic",
            epic_id,
            expected_version,
            epic.version,
        )

    before = _dump(epic)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(epic, field, value)
    session.flush()

    after = _dump(epic)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.EPIC,
        entity_id=epic.id,
        action=AuditAction.UPDATED,
        before=before,
        after=after,
    )
    publish_event(
        session,
        event_type="epic.updated",
        actor=actor,
        entity_type=AuditEntityType.EPIC.value,
        entity_id=epic.id,
        entity_version=epic.version,
        payload=after,
    )
    return epic


def soft_delete_epic(
    session: Session,
    *,
    actor: Actor,
    epic_id: str,
    expected_version: int,
) -> Epic:
    """
    Mark an epic as deleted by stamping ``deleted_at``.

    Does not cascade to the epic's stories. Stories keep their
    ``epic_id`` pointer; callers that want to detach stories from the
    deleted epic must do so explicitly.
    """
    epic = get_epic(session, epic_id=epic_id)
    if epic.version != expected_version:
        raise VersionConflictError(
            "epic",
            epic_id,
            expected_version,
            epic.version,
        )

    before = _dump(epic)
    epic.deleted_at = utc_now_iso()
    session.flush()

    after = _dump(epic)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.EPIC,
        entity_id=epic.id,
        action=AuditAction.SOFT_DELETED,
        before=before,
        after=after,
    )
    publish_event(
        session,
        event_type="epic.deleted",
        actor=actor,
        entity_type=AuditEntityType.EPIC.value,
        entity_id=epic.id,
        entity_version=epic.version,
        payload=after,
    )
    return epic


def close_epic(
    session: Session,
    *,
    actor: Actor,
    epic_id: str,
    expected_version: int,
) -> Epic:
    """
    Convenience wrapper that sets the epic's state to ``closed``.

    Idempotent: closing an already-closed epic returns the epic
    unchanged and does not emit an audit row.
    """
    return _set_state(
        session,
        actor=actor,
        epic_id=epic_id,
        expected_version=expected_version,
        target_state=EpicState.CLOSED,
    )


def reopen_epic(
    session: Session,
    *,
    actor: Actor,
    epic_id: str,
    expected_version: int,
) -> Epic:
    """
    Convenience wrapper that sets the epic's state to ``open``.

    Idempotent: reopening an already-open epic returns the epic
    unchanged and does not emit an audit row.
    """
    return _set_state(
        session,
        actor=actor,
        epic_id=epic_id,
        expected_version=expected_version,
        target_state=EpicState.OPEN,
    )


def _set_state(
    session: Session,
    *,
    actor: Actor,
    epic_id: str,
    expected_version: int,
    target_state: EpicState,
) -> Epic:
    """
    Shared implementation of ``close_epic``/``reopen_epic``.

    Version check always happens so a stale ``If-Match`` is rejected
    even when the transition would otherwise be a no-op; this keeps the
    concurrency contract identical to the other mutating endpoints.
    """
    epic = get_epic(session, epic_id=epic_id)
    if epic.version != expected_version:
        raise VersionConflictError(
            "epic",
            epic_id,
            expected_version,
            epic.version,
        )

    if epic.state == target_state:
        return epic

    before = _dump(epic)
    epic.state = target_state
    session.flush()

    after = _dump(epic)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.EPIC,
        entity_id=epic.id,
        action=AuditAction.UPDATED,
        before=before,
        after=after,
    )
    publish_event(
        session,
        event_type="epic.updated",
        actor=actor,
        entity_type=AuditEntityType.EPIC.value,
        entity_id=epic.id,
        entity_version=epic.version,
        payload=after,
    )
    return epic
