"""
Service-layer tests for comments.

Exercises :mod:`kanberoo_core.services.comments`: create, read, update,
soft-delete, and the one-level threading rule. The load-bearing
invariant asserted throughout is that every successful mutation writes
exactly one ``audit_events`` row with the correct action and actor
attribution.
"""

import json

import pytest
from sqlalchemy.orm import Session

from kanberoo_core import Actor, ActorType
from kanberoo_core.enums import AuditEntityType
from kanberoo_core.models.audit import AuditEvent
from kanberoo_core.schemas.comment import CommentCreate, CommentUpdate
from kanberoo_core.schemas.story import StoryCreate
from kanberoo_core.schemas.workspace import WorkspaceCreate
from kanberoo_core.services import comments as comment_service
from kanberoo_core.services import stories as story_service
from kanberoo_core.services import workspaces as ws_service
from kanberoo_core.services.exceptions import (
    NotFoundError,
    ValidationError,
    VersionConflictError,
)

HUMAN = Actor(type=ActorType.HUMAN, id="adam")
CLAUDE = Actor(type=ActorType.CLAUDE, id="outer-claude")


def _audit_rows(session: Session, entity_id: str) -> list[AuditEvent]:
    """
    Return every audit row for ``entity_id`` in chronological order.
    """
    return (
        session.query(AuditEvent)
        .filter(AuditEvent.entity_id == entity_id)
        .order_by(AuditEvent.occurred_at, AuditEvent.id)
        .all()
    )


def _setup_story(session: Session) -> str:
    """
    Create a workspace and a story; return the story id.
    """
    ws = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanberoo"),
    )
    session.commit()
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=ws.id,
        payload=StoryCreate(title="s"),
    )
    session.commit()
    return story.id


def test_create_comment_emits_audit_and_stamps_actor(session: Session) -> None:
    """
    Creating a comment writes a single ``created`` audit row and stamps
    ``actor_type``/``actor_id`` from the caller's Actor.
    """
    story_id = _setup_story(session)
    comment = comment_service.create_comment(
        session,
        actor=CLAUDE,
        story_id=story_id,
        payload=CommentCreate(body="hello"),
    )
    session.commit()

    assert comment.actor_type == ActorType.CLAUDE
    assert comment.actor_id == "outer-claude"
    assert comment.parent_id is None

    events = _audit_rows(session, comment.id)
    assert len(events) == 1
    assert events[0].action == "created"
    assert events[0].entity_type == AuditEntityType.COMMENT
    assert events[0].actor_type == ActorType.CLAUDE


def test_create_comment_unknown_story_raises_not_found(session: Session) -> None:
    """
    Creating a comment on a missing story raises :class:`NotFoundError`.
    """
    with pytest.raises(NotFoundError):
        comment_service.create_comment(
            session,
            actor=HUMAN,
            story_id="missing",
            payload=CommentCreate(body="hi"),
        )


def test_create_reply_to_top_level_succeeds(session: Session) -> None:
    """
    A reply to a top-level comment is accepted and carries the parent
    pointer.
    """
    story_id = _setup_story(session)
    parent = comment_service.create_comment(
        session,
        actor=HUMAN,
        story_id=story_id,
        payload=CommentCreate(body="top"),
    )
    session.commit()

    reply = comment_service.create_comment(
        session,
        actor=HUMAN,
        story_id=story_id,
        payload=CommentCreate(body="reply", parent_id=parent.id),
    )
    session.commit()

    assert reply.parent_id == parent.id


def test_reply_to_reply_rejected(session: Session) -> None:
    """
    Replies to replies are rejected with :class:`ValidationError`.
    """
    story_id = _setup_story(session)
    parent = comment_service.create_comment(
        session,
        actor=HUMAN,
        story_id=story_id,
        payload=CommentCreate(body="top"),
    )
    session.commit()
    reply = comment_service.create_comment(
        session,
        actor=HUMAN,
        story_id=story_id,
        payload=CommentCreate(body="reply", parent_id=parent.id),
    )
    session.commit()

    with pytest.raises(ValidationError) as exc_info:
        comment_service.create_comment(
            session,
            actor=HUMAN,
            story_id=story_id,
            payload=CommentCreate(body="nope", parent_id=reply.id),
        )
    assert exc_info.value.field == "parent_id"


def test_parent_on_other_story_rejected(session: Session) -> None:
    """
    ``parent_id`` must reference a comment on the same story.
    """
    story_a = _setup_story(session)
    # Second story in a fresh workspace.
    ws_b = ws_service.create_workspace(
        session, actor=HUMAN, payload=WorkspaceCreate(key="BBB", name="b")
    )
    session.commit()
    story_b = story_service.create_story(
        session, actor=HUMAN, workspace_id=ws_b.id, payload=StoryCreate(title="b")
    )
    session.commit()
    parent = comment_service.create_comment(
        session,
        actor=HUMAN,
        story_id=story_a,
        payload=CommentCreate(body="on A"),
    )
    session.commit()

    with pytest.raises(ValidationError):
        comment_service.create_comment(
            session,
            actor=HUMAN,
            story_id=story_b.id,
            payload=CommentCreate(body="cross", parent_id=parent.id),
        )


def test_list_comments_orders_chronologically(session: Session) -> None:
    """
    ``list_comments`` returns a flat list in (created_at, id) order.
    """
    story_id = _setup_story(session)
    for body in ("a", "b", "c"):
        comment_service.create_comment(
            session,
            actor=HUMAN,
            story_id=story_id,
            payload=CommentCreate(body=body),
        )
        session.commit()

    rows = comment_service.list_comments(session, story_id=story_id)
    assert [c.body for c in rows] == ["a", "b", "c"]


def test_update_comment_emits_updated_audit(session: Session) -> None:
    """
    Patching a comment writes an ``updated`` audit row with before/after.
    """
    story_id = _setup_story(session)
    comment = comment_service.create_comment(
        session,
        actor=HUMAN,
        story_id=story_id,
        payload=CommentCreate(body="old"),
    )
    session.commit()

    updated = comment_service.update_comment(
        session,
        actor=HUMAN,
        comment_id=comment.id,
        expected_version=comment.version,
        payload=CommentUpdate(body="new"),
    )
    session.commit()

    assert updated.body == "new"
    assert updated.version == 2

    events = _audit_rows(session, comment.id)
    assert [e.action for e in events] == ["created", "updated"]
    diff = json.loads(events[1].diff)
    assert diff["before"]["body"] == "old"
    assert diff["after"]["body"] == "new"


def test_update_comment_stale_version_rejected(session: Session) -> None:
    """
    A stale ``expected_version`` raises :class:`VersionConflictError`
    with no audit row written.
    """
    story_id = _setup_story(session)
    comment = comment_service.create_comment(
        session,
        actor=HUMAN,
        story_id=story_id,
        payload=CommentCreate(body="x"),
    )
    session.commit()

    with pytest.raises(VersionConflictError):
        comment_service.update_comment(
            session,
            actor=HUMAN,
            comment_id=comment.id,
            expected_version=99,
            payload=CommentUpdate(body="no"),
        )
    session.rollback()
    assert [e.action for e in _audit_rows(session, comment.id)] == ["created"]


def test_soft_delete_comment_hides_and_audits(session: Session) -> None:
    """
    Soft-delete stamps ``deleted_at``, emits an audit row, and hides
    the row from the default :func:`get_comment` path.
    """
    story_id = _setup_story(session)
    comment = comment_service.create_comment(
        session,
        actor=HUMAN,
        story_id=story_id,
        payload=CommentCreate(body="x"),
    )
    session.commit()

    comment_service.soft_delete_comment(
        session,
        actor=HUMAN,
        comment_id=comment.id,
        expected_version=comment.version,
    )
    session.commit()

    events = _audit_rows(session, comment.id)
    assert [e.action for e in events] == ["created", "soft_deleted"]

    with pytest.raises(NotFoundError):
        comment_service.get_comment(session, comment_id=comment.id)

    restored = comment_service.get_comment(
        session, comment_id=comment.id, include_deleted=True
    )
    assert restored.id == comment.id


def test_soft_delete_does_not_cascade_to_replies(session: Session) -> None:
    """
    Soft-deleting a parent comment leaves its replies visible;
    ``parent_id`` continues to point at the deleted row.
    """
    story_id = _setup_story(session)
    parent = comment_service.create_comment(
        session,
        actor=HUMAN,
        story_id=story_id,
        payload=CommentCreate(body="parent"),
    )
    session.commit()
    reply = comment_service.create_comment(
        session,
        actor=HUMAN,
        story_id=story_id,
        payload=CommentCreate(body="reply", parent_id=parent.id),
    )
    session.commit()

    comment_service.soft_delete_comment(
        session,
        actor=HUMAN,
        comment_id=parent.id,
        expected_version=parent.version,
    )
    session.commit()

    live = comment_service.list_comments(session, story_id=story_id)
    assert [c.id for c in live] == [reply.id]
    reread = comment_service.get_comment(session, comment_id=reply.id)
    assert reread.parent_id == parent.id
