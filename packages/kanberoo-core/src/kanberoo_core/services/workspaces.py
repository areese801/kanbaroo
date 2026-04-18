"""
Workspace CRUD service.

Every public function here is the service-layer entry point for one
REST endpoint. All mutations flow through this module so audit emission
is guaranteed: an endpoint cannot skip it by calling SQLAlchemy
directly, because the convention is that endpoints only ever call
service functions.

Soft deletes do not cascade to children. Per ``docs/spec.md`` section
3.4, cascading is the responsibility of explicit service logic in the
milestone that owns the child entity. This module therefore refuses to
hard-delete and only toggles ``deleted_at``.
"""

import base64
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kanberoo_core.actor import Actor
from kanberoo_core.enums import AuditAction, AuditEntityType
from kanberoo_core.models.workspace import Workspace
from kanberoo_core.queries import live
from kanberoo_core.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceUpdate,
)
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


def _dump(workspace: Workspace) -> dict[str, Any]:
    """
    Serialise a :class:`Workspace` row into a JSON-friendly dict for
    the audit log.
    """
    return WorkspaceRead.model_validate(workspace).model_dump(mode="json")


def _encode_cursor(workspace_id: str) -> str:
    """
    Encode a workspace id as an opaque URL-safe cursor.

    The cursor is not meant to be interpretable by clients; wrapping the
    id in base64 is purely to signal that fact.
    """
    return base64.urlsafe_b64encode(workspace_id.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> str:
    """
    Decode a cursor back into the workspace id it wraps.

    Raises :class:`ValidationError` if the cursor is not valid base64
    URL-safe data; this translates to a 400 at the API layer.
    """
    try:
        return base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("cursor", "malformed cursor value") from exc


def create_workspace(
    session: Session,
    *,
    actor: Actor,
    payload: WorkspaceCreate,
) -> Workspace:
    """
    Create a new workspace and emit an audit event.

    Duplicate ``key`` values are rejected with :class:`ValidationError`
    before the INSERT is attempted, yielding a cleaner error than the
    underlying ``UNIQUE`` constraint violation.
    """
    existing = session.execute(
        select(Workspace).where(Workspace.key == payload.key)
    ).scalar_one_or_none()
    if existing is not None:
        raise ValidationError(
            "key",
            f"workspace key {payload.key!r} already in use",
        )

    workspace = Workspace(
        key=payload.key,
        name=payload.name,
        description=payload.description,
    )
    session.add(workspace)
    session.flush()

    after = _dump(workspace)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.WORKSPACE,
        entity_id=workspace.id,
        action=AuditAction.CREATED,
        before=None,
        after=after,
    )
    publish_event(
        session,
        event_type="workspace.created",
        actor=actor,
        entity_type=AuditEntityType.WORKSPACE.value,
        entity_id=workspace.id,
        entity_version=workspace.version,
        payload=after,
    )
    return workspace


def list_workspaces(
    session: Session,
    *,
    include_deleted: bool = False,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> tuple[list[Workspace], str | None]:
    """
    Return a page of workspaces plus a cursor for the next page.

    Ordering is by ``id`` (UUID v7: time-sortable). The cursor wraps the
    last id on the current page; the next request resumes strictly
    after it. ``limit`` is clamped to the inclusive range
    ``[1, MAX_PAGE_LIMIT]``.
    """
    if limit < 1:
        limit = 1
    if limit > MAX_PAGE_LIMIT:
        limit = MAX_PAGE_LIMIT

    stmt = select(Workspace).order_by(Workspace.id)
    if not include_deleted:
        stmt = live(stmt, Workspace)
    if cursor is not None:
        stmt = stmt.where(Workspace.id > _decode_cursor(cursor))
    stmt = stmt.limit(limit + 1)

    rows = list(session.execute(stmt).scalars().all())
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1].id)
    return rows, next_cursor


def get_workspace(
    session: Session,
    *,
    workspace_id: str,
    include_deleted: bool = False,
) -> Workspace:
    """
    Return a workspace by id or raise :class:`NotFoundError`.

    By default soft-deleted rows are treated as missing. Callers that
    need to read an archived workspace (admin tools, audit views) pass
    ``include_deleted=True``.
    """
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise NotFoundError("workspace", workspace_id)
    if workspace.deleted_at is not None and not include_deleted:
        raise NotFoundError("workspace", workspace_id)
    return workspace


def get_workspace_by_key(
    session: Session,
    *,
    key: str,
    include_deleted: bool = False,
) -> Workspace:
    """
    Return a workspace by its short ``key`` or raise
    :class:`NotFoundError`.

    Mirrors :func:`kanberoo_core.services.stories.get_story_by_human_id`:
    callers with a human-meaningful handle (``KAN``) can resolve to a
    full workspace without a list scan. Soft-deleted rows are hidden
    unless ``include_deleted`` is ``True``.
    """
    stmt = select(Workspace).where(Workspace.key == key)
    workspace = session.execute(stmt).scalar_one_or_none()
    if workspace is None:
        raise NotFoundError("workspace", key)
    if workspace.deleted_at is not None and not include_deleted:
        raise NotFoundError("workspace", key)
    return workspace


def update_workspace(
    session: Session,
    *,
    actor: Actor,
    workspace_id: str,
    expected_version: int,
    payload: WorkspaceUpdate,
) -> Workspace:
    """
    Apply a ``PATCH`` payload to a workspace.

    Enforces optimistic concurrency: the caller supplies the ``version``
    they read, and a mismatch raises :class:`VersionConflictError`.
    Only fields explicitly set in ``payload`` are updated; the Pydantic
    ``WorkspaceUpdate`` model's ``model_dump(exclude_unset=True)`` is
    what distinguishes "unset" from "set to null".
    """
    workspace = get_workspace(session, workspace_id=workspace_id)
    if workspace.version != expected_version:
        raise VersionConflictError(
            "workspace",
            workspace_id,
            expected_version,
            workspace.version,
        )

    before = _dump(workspace)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(workspace, field, value)
    session.flush()

    after = _dump(workspace)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.WORKSPACE,
        entity_id=workspace.id,
        action=AuditAction.UPDATED,
        before=before,
        after=after,
    )
    publish_event(
        session,
        event_type="workspace.updated",
        actor=actor,
        entity_type=AuditEntityType.WORKSPACE.value,
        entity_id=workspace.id,
        entity_version=workspace.version,
        payload=after,
    )
    return workspace


def soft_delete_workspace(
    session: Session,
    *,
    actor: Actor,
    workspace_id: str,
    expected_version: int,
) -> Workspace:
    """
    Mark a workspace as deleted by stamping ``deleted_at``.

    Does not cascade to epics, stories, or repos: per ``docs/spec.md``
    section 3.4, soft deletes are an explicit per-entity operation and
    that cascade will be added when those resources get service layers
    in a later milestone.
    """
    workspace = get_workspace(session, workspace_id=workspace_id)
    if workspace.version != expected_version:
        raise VersionConflictError(
            "workspace",
            workspace_id,
            expected_version,
            workspace.version,
        )

    before = _dump(workspace)
    workspace.deleted_at = utc_now_iso()
    session.flush()

    after = _dump(workspace)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.WORKSPACE,
        entity_id=workspace.id,
        action=AuditAction.SOFT_DELETED,
        before=before,
        after=after,
    )
    publish_event(
        session,
        event_type="workspace.deleted",
        actor=actor,
        entity_type=AuditEntityType.WORKSPACE.value,
        entity_id=workspace.id,
        entity_version=workspace.version,
        payload=after,
    )
    return workspace
