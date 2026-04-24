"""
Service-layer tests for tags.

Covers the full tag surface: create (with workspace-scoped uniqueness),
list, rename/recolor via update, soft-delete (which detaches from
stories), and the add/remove association helpers. Audit rules under
test:

* Tag mutations (create, update, soft_delete) emit exactly one audit
  row against the tag.
* Soft-deleting a tag does **not** emit per-story audit rows; the
  association cleanup is a service-level detail.
* ``add_tags_to_story`` emits one ``tag_added`` row per tag newly
  associated, on the story.
* ``remove_tag_from_story`` emits one ``tag_removed`` row only when an
  association was actually removed.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from kanbaroo_core import Actor, ActorType
from kanbaroo_core.enums import AuditEntityType
from kanbaroo_core.models.audit import AuditEvent
from kanbaroo_core.models.story_tag import story_tags
from kanbaroo_core.schemas.story import StoryCreate
from kanbaroo_core.schemas.tag import TagCreate, TagUpdate
from kanbaroo_core.schemas.workspace import WorkspaceCreate
from kanbaroo_core.services import stories as story_service
from kanbaroo_core.services import tags as tag_service
from kanbaroo_core.services import workspaces as ws_service
from kanbaroo_core.services.exceptions import (
    NotFoundError,
    ValidationError,
)

HUMAN = Actor(type=ActorType.HUMAN, id="adam")


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


def _make_workspace(session: Session, *, key: str = "KAN") -> str:
    """
    Create a workspace and return its id.
    """
    ws = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key=key, name=f"{key} workspace"),
    )
    session.commit()
    return ws.id


def _make_story(session: Session, workspace_id: str, *, title: str = "s") -> str:
    """
    Create a story and return its id.
    """
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title=title),
    )
    session.commit()
    return story.id


def test_create_tag_emits_audit(session: Session) -> None:
    """
    Creating a tag emits a single ``created`` audit row.
    """
    ws_id = _make_workspace(session)
    tag = tag_service.create_tag(
        session,
        actor=HUMAN,
        workspace_id=ws_id,
        payload=TagCreate(name="bug", color="#cc3333"),
    )
    session.commit()

    events = _audit_rows(session, tag.id)
    assert [e.action for e in events] == ["created"]
    assert events[0].entity_type == AuditEntityType.TAG


def test_tag_name_unique_within_workspace(session: Session) -> None:
    """
    Duplicate tag names in the same workspace are rejected as
    :class:`ValidationError`.
    """
    ws_id = _make_workspace(session)
    tag_service.create_tag(
        session, actor=HUMAN, workspace_id=ws_id, payload=TagCreate(name="bug")
    )
    session.commit()

    with pytest.raises(ValidationError) as exc:
        tag_service.create_tag(
            session, actor=HUMAN, workspace_id=ws_id, payload=TagCreate(name="bug")
        )
    assert exc.value.field == "name"


def test_same_name_different_workspaces_is_distinct(session: Session) -> None:
    """
    A tag named ``bug`` in workspace A is distinct from ``bug`` in
    workspace B.
    """
    ws_a = _make_workspace(session, key="AAA")
    ws_b = _make_workspace(session, key="BBB")
    tag_service.create_tag(
        session, actor=HUMAN, workspace_id=ws_a, payload=TagCreate(name="bug")
    )
    tag_service.create_tag(
        session, actor=HUMAN, workspace_id=ws_b, payload=TagCreate(name="bug")
    )
    session.commit()

    a_tags = tag_service.list_tags(session, workspace_id=ws_a)
    b_tags = tag_service.list_tags(session, workspace_id=ws_b)
    assert len(a_tags) == 1
    assert len(b_tags) == 1
    assert a_tags[0].id != b_tags[0].id


def test_rename_tag_emits_updated(session: Session) -> None:
    """
    Renaming a tag emits an ``updated`` audit row; the rename history
    lives in the diff.
    """
    ws_id = _make_workspace(session)
    tag = tag_service.create_tag(
        session, actor=HUMAN, workspace_id=ws_id, payload=TagCreate(name="old")
    )
    session.commit()

    renamed = tag_service.update_tag(
        session,
        actor=HUMAN,
        tag_id=tag.id,
        payload=TagUpdate(name="new"),
    )
    session.commit()

    assert renamed.name == "new"
    events = _audit_rows(session, tag.id)
    assert [e.action for e in events] == ["created", "updated"]


def test_rename_collision_rejected(session: Session) -> None:
    """
    Renaming a tag to an existing name in the same workspace is
    rejected.
    """
    ws_id = _make_workspace(session)
    tag_service.create_tag(
        session, actor=HUMAN, workspace_id=ws_id, payload=TagCreate(name="bug")
    )
    other = tag_service.create_tag(
        session, actor=HUMAN, workspace_id=ws_id, payload=TagCreate(name="feat")
    )
    session.commit()

    with pytest.raises(ValidationError):
        tag_service.update_tag(
            session,
            actor=HUMAN,
            tag_id=other.id,
            payload=TagUpdate(name="bug"),
        )


def test_soft_delete_tag_detaches_from_stories(session: Session) -> None:
    """
    Soft-deleting a tag removes every ``story_tags`` row referencing it
    and emits only a single ``soft_deleted`` row on the tag itself.
    """
    ws_id = _make_workspace(session)
    tag = tag_service.create_tag(
        session, actor=HUMAN, workspace_id=ws_id, payload=TagCreate(name="bug")
    )
    session.commit()

    story_id = _make_story(session, ws_id)
    tag_service.add_tags_to_story(
        session, actor=HUMAN, story_id=story_id, tag_ids=[tag.id]
    )
    session.commit()

    # Before delete: association exists.
    assoc = session.execute(
        select(story_tags).where(story_tags.c.tag_id == tag.id)
    ).all()
    assert len(assoc) == 1

    tag_service.soft_delete_tag(session, actor=HUMAN, tag_id=tag.id)
    session.commit()

    # After delete: association gone.
    assoc_after = session.execute(
        select(story_tags).where(story_tags.c.tag_id == tag.id)
    ).all()
    assert assoc_after == []

    # Tag audit trail: created, tag_added (this is on the STORY, not tag),
    # then soft_deleted on the tag. The tag's own audit only shows
    # created + soft_deleted.
    tag_events = _audit_rows(session, tag.id)
    assert [e.action for e in tag_events] == ["created", "soft_deleted"]

    # Story events include tag_added but no tag_removed (since the cleanup
    # is a service-level detail).
    story_events = _audit_rows(session, story_id)
    assert "tag_added" in [e.action for e in story_events]
    assert "tag_removed" not in [e.action for e in story_events]


def test_add_tags_to_story_emits_one_per_tag(session: Session) -> None:
    """
    ``add_tags_to_story`` emits exactly one ``tag_added`` row per new
    association on the story.
    """
    ws_id = _make_workspace(session)
    tag_a = tag_service.create_tag(
        session, actor=HUMAN, workspace_id=ws_id, payload=TagCreate(name="a")
    )
    tag_b = tag_service.create_tag(
        session, actor=HUMAN, workspace_id=ws_id, payload=TagCreate(name="b")
    )
    session.commit()
    story_id = _make_story(session, ws_id)

    tag_service.add_tags_to_story(
        session,
        actor=HUMAN,
        story_id=story_id,
        tag_ids=[tag_a.id, tag_b.id],
    )
    session.commit()

    story_events = [
        e for e in _audit_rows(session, story_id) if e.action == "tag_added"
    ]
    assert len(story_events) == 2


def test_add_tags_is_idempotent(session: Session) -> None:
    """
    Re-adding an already-associated tag is a no-op and does not emit a
    duplicate audit row.
    """
    ws_id = _make_workspace(session)
    tag = tag_service.create_tag(
        session, actor=HUMAN, workspace_id=ws_id, payload=TagCreate(name="a")
    )
    session.commit()
    story_id = _make_story(session, ws_id)

    tag_service.add_tags_to_story(
        session, actor=HUMAN, story_id=story_id, tag_ids=[tag.id]
    )
    session.commit()
    tag_service.add_tags_to_story(
        session, actor=HUMAN, story_id=story_id, tag_ids=[tag.id]
    )
    session.commit()

    added_events = [
        e for e in _audit_rows(session, story_id) if e.action == "tag_added"
    ]
    assert len(added_events) == 1


def test_cross_workspace_tagging_rejected(session: Session) -> None:
    """
    Attaching a tag from a different workspace to a story is rejected.
    """
    ws_a = _make_workspace(session, key="AAA")
    ws_b = _make_workspace(session, key="BBB")
    tag_b = tag_service.create_tag(
        session, actor=HUMAN, workspace_id=ws_b, payload=TagCreate(name="b")
    )
    session.commit()
    story_a = _make_story(session, ws_a)

    with pytest.raises(ValidationError):
        tag_service.add_tags_to_story(
            session, actor=HUMAN, story_id=story_a, tag_ids=[tag_b.id]
        )


def test_remove_tag_from_story_emits_once(session: Session) -> None:
    """
    Removing an existing association emits one ``tag_removed`` row.
    """
    ws_id = _make_workspace(session)
    tag = tag_service.create_tag(
        session, actor=HUMAN, workspace_id=ws_id, payload=TagCreate(name="a")
    )
    session.commit()
    story_id = _make_story(session, ws_id)
    tag_service.add_tags_to_story(
        session, actor=HUMAN, story_id=story_id, tag_ids=[tag.id]
    )
    session.commit()

    tag_service.remove_tag_from_story(
        session, actor=HUMAN, story_id=story_id, tag_id=tag.id
    )
    session.commit()

    events = [e for e in _audit_rows(session, story_id) if e.action == "tag_removed"]
    assert len(events) == 1


def test_remove_tag_noop_does_not_emit(session: Session) -> None:
    """
    Removing a tag that was never associated is a silent no-op and
    emits no audit row.
    """
    ws_id = _make_workspace(session)
    tag = tag_service.create_tag(
        session, actor=HUMAN, workspace_id=ws_id, payload=TagCreate(name="a")
    )
    session.commit()
    story_id = _make_story(session, ws_id)

    tag_service.remove_tag_from_story(
        session, actor=HUMAN, story_id=story_id, tag_id=tag.id
    )
    session.commit()

    events = [e for e in _audit_rows(session, story_id) if e.action == "tag_removed"]
    assert events == []


def test_soft_delete_unknown_tag_raises(session: Session) -> None:
    """
    Soft-deleting an unknown tag raises :class:`NotFoundError`.
    """
    with pytest.raises(NotFoundError):
        tag_service.soft_delete_tag(session, actor=HUMAN, tag_id="missing")
