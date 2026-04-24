"""
Comment CRUD service.

Comments are markdown attached to a story. The spec permits one level
of threading via ``parent_id``; replies cannot themselves have replies.
That rule is enforced here (not in the database) so violations surface
as :class:`ValidationError` with a helpful message rather than a raw
integrity error.

Comments are actor-attributed: every row carries ``actor_type`` and
``actor_id`` stamped at creation from the caller's :class:`Actor`.
Updates do not change attribution; the original author is preserved.

Per the project's soft-delete-does-not-cascade rule, soft-deleting a
top-level comment does **not** soft-delete its replies. Clients that
care about dangling parent pointers can render "parent deleted" on
their own; the audit row on the deleted parent is the authoritative
record.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kanbaroo_core.actor import Actor
from kanbaroo_core.enums import AuditAction, AuditEntityType
from kanbaroo_core.models.comment import Comment
from kanbaroo_core.models.story import Story
from kanbaroo_core.queries import live
from kanbaroo_core.schemas.comment import CommentCreate, CommentRead, CommentUpdate
from kanbaroo_core.services.audit import emit_audit
from kanbaroo_core.services.events import publish_event
from kanbaroo_core.services.exceptions import (
    NotFoundError,
    ValidationError,
    VersionConflictError,
)
from kanbaroo_core.time import utc_now_iso


def _dump(comment: Comment) -> dict[str, Any]:
    """
    Serialise a :class:`Comment` row into a JSON-friendly dict for the
    audit log.
    """
    return CommentRead.model_validate(comment).model_dump(mode="json")


def _get_live_story(session: Session, story_id: str) -> Story:
    """
    Return a live story by id or raise :class:`NotFoundError`.

    Soft-deleted stories are hidden from the comment surface: a client
    should not be posting to (or listing comments on) an archived
    story. Callers that genuinely need comments on a deleted story
    should go through the audit log.
    """
    story = session.get(Story, story_id)
    if story is None or story.deleted_at is not None:
        raise NotFoundError("story", story_id)
    return story


def create_comment(
    session: Session,
    *,
    actor: Actor,
    story_id: str,
    payload: CommentCreate,
) -> Comment:
    """
    Create a new comment on ``story_id`` and emit a ``created`` audit
    row.

    If ``payload.parent_id`` is set, the referenced comment must exist,
    must belong to the same story, and must itself be top-level
    (``parent_id is None``). Violations raise :class:`ValidationError`
    so the API returns 400 rather than surfacing a stale row.
    """
    _get_live_story(session, story_id)

    if payload.parent_id is not None:
        parent = session.get(Comment, payload.parent_id)
        if parent is None or parent.deleted_at is not None:
            raise ValidationError(
                "parent_id",
                f"parent comment {payload.parent_id!r} not found",
            )
        if parent.story_id != story_id:
            raise ValidationError(
                "parent_id",
                "parent comment belongs to a different story",
            )
        if parent.parent_id is not None:
            raise ValidationError(
                "parent_id",
                "replies cannot have replies",
            )

    comment = Comment(
        story_id=story_id,
        parent_id=payload.parent_id,
        body=payload.body,
        actor_type=actor.type,
        actor_id=actor.id,
    )
    session.add(comment)
    session.flush()

    after = _dump(comment)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.COMMENT,
        entity_id=comment.id,
        action=AuditAction.CREATED,
        before=None,
        after=after,
    )
    # Comment creation is surfaced as ``story.commented`` per spec
    # §5.4: the event is a child event of the story, so
    # ``entity_type`` / ``entity_id`` point at the story. The story's
    # version does not change when a comment is added, so
    # ``entity_version`` is ``None``; clients that want the story
    # version refetch via REST.
    publish_event(
        session,
        event_type="story.commented",
        actor=actor,
        entity_type=AuditEntityType.STORY.value,
        entity_id=story_id,
        entity_version=None,
        payload=after,
    )
    return comment


def list_comments(
    session: Session,
    *,
    story_id: str,
    include_deleted: bool = False,
) -> list[Comment]:
    """
    Return every comment on ``story_id`` as a flat chronological list.

    Ordering is ``(created_at ASC, id ASC)``. Clients reconstruct the
    thread by grouping by ``parent_id``. No pagination: comments per
    story are expected to stay small and the spec surface does not call
    for a cursor here. If a story grows large enough that this matters,
    the list endpoint can be retrofitted with cursors without a schema
    change.
    """
    stmt = (
        select(Comment)
        .where(Comment.story_id == story_id)
        .order_by(Comment.created_at, Comment.id)
    )
    if not include_deleted:
        stmt = live(stmt, Comment)
    return list(session.execute(stmt).scalars().all())


def get_comment(
    session: Session,
    *,
    comment_id: str,
    include_deleted: bool = False,
) -> Comment:
    """
    Return a comment by id or raise :class:`NotFoundError`.

    Soft-deleted rows are hidden by default; pass
    ``include_deleted=True`` to read an archived comment.
    """
    comment = session.get(Comment, comment_id)
    if comment is None:
        raise NotFoundError("comment", comment_id)
    if comment.deleted_at is not None and not include_deleted:
        raise NotFoundError("comment", comment_id)
    return comment


def update_comment(
    session: Session,
    *,
    actor: Actor,
    comment_id: str,
    expected_version: int,
    payload: CommentUpdate,
) -> Comment:
    """
    Apply a ``PATCH`` payload to a comment.

    Only ``body`` is patchable; ``parent_id`` is intentionally immutable
    after creation so the thread shape cannot be rewritten under
    readers. The original ``actor_type`` / ``actor_id`` stamp is
    likewise preserved: authorship tracks who wrote the comment, not
    who most recently edited it.
    """
    comment = get_comment(session, comment_id=comment_id)
    if comment.version != expected_version:
        raise VersionConflictError(
            "comment",
            comment_id,
            expected_version,
            comment.version,
        )

    updates = payload.model_dump(exclude_unset=True)
    if "body" not in updates:
        return comment

    before = _dump(comment)
    comment.body = updates["body"]
    session.flush()

    after = _dump(comment)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.COMMENT,
        entity_id=comment.id,
        action=AuditAction.UPDATED,
        before=before,
        after=after,
    )
    publish_event(
        session,
        event_type="comment.updated",
        actor=actor,
        entity_type=AuditEntityType.COMMENT.value,
        entity_id=comment.id,
        entity_version=comment.version,
        payload=after,
    )
    return comment


def soft_delete_comment(
    session: Session,
    *,
    actor: Actor,
    comment_id: str,
    expected_version: int,
) -> Comment:
    """
    Mark a comment as deleted by stamping ``deleted_at``.

    Soft delete does not cascade to replies; they retain their
    ``parent_id`` pointer at the orphaned row. See the module docstring
    for the rationale.
    """
    comment = get_comment(session, comment_id=comment_id)
    if comment.version != expected_version:
        raise VersionConflictError(
            "comment",
            comment_id,
            expected_version,
            comment.version,
        )

    before = _dump(comment)
    comment.deleted_at = utc_now_iso()
    session.flush()

    after = _dump(comment)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.COMMENT,
        entity_id=comment.id,
        action=AuditAction.SOFT_DELETED,
        before=before,
        after=after,
    )
    publish_event(
        session,
        event_type="comment.deleted",
        actor=actor,
        entity_type=AuditEntityType.COMMENT.value,
        entity_id=comment.id,
        entity_version=comment.version,
        payload=after,
    )
    return comment
