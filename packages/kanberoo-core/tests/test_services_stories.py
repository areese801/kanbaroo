"""
Service-layer tests for stories.

Covers the full CRUD surface plus the state-machine transition logic.
The transition tests walk every valid edge documented in
``docs/spec.md`` section 4.3 and spot-check a representative sample of
invalid moves so regressions in :data:`_ALLOWED_TRANSITIONS` surface
immediately.
"""

import json

import pytest
from sqlalchemy.orm import Session

from kanberoo_core import Actor, ActorType
from kanberoo_core.enums import AuditEntityType, StoryPriority, StoryState
from kanberoo_core.models.audit import AuditEvent
from kanberoo_core.schemas.epic import EpicCreate
from kanberoo_core.schemas.story import StoryCreate, StoryUpdate
from kanberoo_core.schemas.workspace import WorkspaceCreate
from kanberoo_core.services import epics as epic_service
from kanberoo_core.services import stories as story_service
from kanberoo_core.services import workspaces as ws_service
from kanberoo_core.services.exceptions import (
    NotFoundError,
    ValidationError,
    VersionConflictError,
)
from kanberoo_core.services.stories import InvalidStateTransitionError

HUMAN = Actor(type=ActorType.HUMAN, id="adam")
CLAUDE = Actor(type=ActorType.CLAUDE, id="outer-claude")


def _audit_rows(session: Session, entity_id: str) -> list[AuditEvent]:
    """
    Return every audit row for the given entity, chronologically.
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


def _make_epic(session: Session, workspace_id: str, *, title: str = "epic") -> str:
    """
    Create an epic and return its id.
    """
    ep = epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=EpicCreate(title=title),
    )
    session.commit()
    return ep.id


def _advance(
    session: Session, story_id: str, to_state: StoryState, actor: Actor = HUMAN
) -> None:
    """
    Transition a story into ``to_state`` using its current version.
    """
    current = story_service.get_story(session, story_id=story_id)
    story_service.transition_story(
        session,
        actor=actor,
        story_id=story_id,
        expected_version=current.version,
        to_state=to_state,
    )
    session.commit()


def test_create_story_emits_audit_and_allocates_human_id(session: Session) -> None:
    """
    Creating a story writes a single ``created`` audit row and assigns
    the next workspace human id.
    """
    workspace_id = _make_workspace(session)
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="write the spec"),
    )
    session.commit()

    assert story.human_id == "KAN-1"
    assert story.state == StoryState.BACKLOG
    events = _audit_rows(session, story.id)
    assert len(events) == 1
    row = events[0]
    assert row.entity_type == AuditEntityType.STORY
    assert row.action == "created"
    diff = json.loads(row.diff)
    assert diff["before"] is None
    assert diff["after"]["state"] == "backlog"


def test_human_ids_are_sequential_across_stories_and_epics(
    session: Session,
) -> None:
    """
    Stories and epics share a single counter per workspace, so their
    human ids interleave without collision.
    """
    workspace_id = _make_workspace(session, key="KAN")

    s1 = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="one"),
    )
    session.commit()

    e1 = epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=EpicCreate(title="first epic"),
    )
    session.commit()

    s2 = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="two"),
    )
    session.commit()

    assert [s1.human_id, e1.human_id, s2.human_id] == [
        "KAN-1",
        "KAN-2",
        "KAN-3",
    ]


def test_create_story_with_epic_in_other_workspace_rejected(
    session: Session,
) -> None:
    """
    ``create_story`` rejects an ``epic_id`` that belongs to a different
    workspace with :class:`ValidationError`.
    """
    ws_a = _make_workspace(session, key="AAA")
    ws_b = _make_workspace(session, key="BBB")
    epic_id_in_a = _make_epic(session, ws_a)

    with pytest.raises(ValidationError):
        story_service.create_story(
            session,
            actor=HUMAN,
            workspace_id=ws_b,
            payload=StoryCreate(title="cross", epic_id=epic_id_in_a),
        )


def test_create_story_with_soft_deleted_epic_rejected(session: Session) -> None:
    """
    Creating a story pointing at a soft-deleted epic is rejected.
    """
    workspace_id = _make_workspace(session)
    epic_id = _make_epic(session, workspace_id)
    original = epic_service.get_epic(session, epic_id=epic_id)
    epic_service.soft_delete_epic(
        session,
        actor=HUMAN,
        epic_id=epic_id,
        expected_version=original.version,
    )
    session.commit()

    with pytest.raises(ValidationError):
        story_service.create_story(
            session,
            actor=HUMAN,
            workspace_id=workspace_id,
            payload=StoryCreate(title="orphan", epic_id=epic_id),
        )


def test_update_story_rejects_cross_workspace_epic_reassignment(
    session: Session,
) -> None:
    """
    Per spec section 10 Q3, reassigning a story to an epic in another
    workspace is rejected rather than silently moving the story.
    """
    ws_a = _make_workspace(session, key="AAA")
    ws_b = _make_workspace(session, key="BBB")
    epic_in_b = _make_epic(session, ws_b)
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=ws_a,
        payload=StoryCreate(title="s1"),
    )
    session.commit()

    with pytest.raises(ValidationError):
        story_service.update_story(
            session,
            actor=HUMAN,
            story_id=story.id,
            expected_version=story.version,
            payload=StoryUpdate(epic_id=epic_in_b),
        )


def test_update_story_within_same_workspace_epic_ok(session: Session) -> None:
    """
    Assigning a story to an epic in the same workspace is allowed and
    produces an ``updated`` audit row.
    """
    workspace_id = _make_workspace(session)
    epic_id = _make_epic(session, workspace_id)
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="s"),
    )
    session.commit()

    updated = story_service.update_story(
        session,
        actor=HUMAN,
        story_id=story.id,
        expected_version=story.version,
        payload=StoryUpdate(epic_id=epic_id),
    )
    session.commit()

    assert updated.epic_id == epic_id
    events = _audit_rows(session, story.id)
    assert [e.action for e in events] == ["created", "updated"]


def test_update_story_detach_from_epic_is_allowed(session: Session) -> None:
    """
    Explicitly setting ``epic_id`` to ``None`` detaches the story from
    its current epic.
    """
    workspace_id = _make_workspace(session)
    epic_id = _make_epic(session, workspace_id)
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="s", epic_id=epic_id),
    )
    session.commit()

    detached = story_service.update_story(
        session,
        actor=HUMAN,
        story_id=story.id,
        expected_version=story.version,
        payload=StoryUpdate(epic_id=None),
    )
    session.commit()

    assert detached.epic_id is None


def test_soft_delete_story_emits_audit_and_hides(session: Session) -> None:
    """
    Soft-delete stamps ``deleted_at``, writes a ``soft_deleted`` row,
    and hides the story from the default read path.
    """
    workspace_id = _make_workspace(session)
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="s"),
    )
    session.commit()
    story_service.soft_delete_story(
        session,
        actor=HUMAN,
        story_id=story.id,
        expected_version=story.version,
    )
    session.commit()

    assert [e.action for e in _audit_rows(session, story.id)] == [
        "created",
        "soft_deleted",
    ]
    with pytest.raises(NotFoundError):
        story_service.get_story(session, story_id=story.id)


VALID_TRANSITIONS: list[tuple[list[StoryState], StoryState]] = [
    ([StoryState.TODO], StoryState.TODO),  # trivial single hop
]


def test_transition_backlog_to_todo_stamps_actor_and_audit(
    session: Session,
) -> None:
    """
    A successful ``backlog -> todo`` move stamps the story's
    ``state_actor_*`` and writes a ``state_changed`` audit row whose
    ``after`` diff carries the new state and actor fields plus any
    supplied ``transition_reason``.
    """
    workspace_id = _make_workspace(session)
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="s"),
    )
    session.commit()

    moved = story_service.transition_story(
        session,
        actor=CLAUDE,
        story_id=story.id,
        expected_version=story.version,
        to_state=StoryState.TODO,
        reason="picked up for sprint",
    )
    session.commit()

    assert moved.state == StoryState.TODO
    assert moved.state_actor_type == ActorType.CLAUDE
    assert moved.state_actor_id == "outer-claude"

    events = _audit_rows(session, story.id)
    assert [e.action for e in events] == ["created", "state_changed"]
    diff = json.loads(events[1].diff)
    assert diff["before"]["state"] == "backlog"
    assert diff["after"]["state"] == "todo"
    assert diff["after"]["state_actor_type"] == "claude"
    assert diff["after"]["state_actor_id"] == "outer-claude"
    assert diff["after"]["transition_reason"] == "picked up for sprint"


def test_full_happy_path_walk(session: Session) -> None:
    """
    Walk a story through every forward edge of the spec's state
    machine: backlog -> todo -> in_progress -> in_review -> done.
    """
    workspace_id = _make_workspace(session)
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="s"),
    )
    session.commit()

    _advance(session, story.id, StoryState.TODO)
    _advance(session, story.id, StoryState.IN_PROGRESS)
    _advance(session, story.id, StoryState.IN_REVIEW)
    _advance(session, story.id, StoryState.DONE)

    assert story_service.get_story(session, story_id=story.id).state == (
        StoryState.DONE
    )
    actions = [e.action for e in _audit_rows(session, story.id)]
    assert actions == [
        "created",
        "state_changed",
        "state_changed",
        "state_changed",
        "state_changed",
    ]


def test_rework_loop_in_review_to_in_progress(session: Session) -> None:
    """
    The rework loop ``in_review -> in_progress`` is allowed.
    """
    workspace_id = _make_workspace(session)
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="s"),
    )
    session.commit()
    _advance(session, story.id, StoryState.TODO)
    _advance(session, story.id, StoryState.IN_PROGRESS)
    _advance(session, story.id, StoryState.IN_REVIEW)
    _advance(session, story.id, StoryState.IN_PROGRESS)

    assert story_service.get_story(session, story_id=story.id).state == (
        StoryState.IN_PROGRESS
    )


def test_reopen_done_to_in_review(session: Session) -> None:
    """
    ``done -> in_review`` (the reopen edge) is allowed.
    """
    workspace_id = _make_workspace(session)
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="s"),
    )
    session.commit()
    for state in [
        StoryState.TODO,
        StoryState.IN_PROGRESS,
        StoryState.IN_REVIEW,
        StoryState.DONE,
    ]:
        _advance(session, story.id, state)

    _advance(session, story.id, StoryState.IN_REVIEW)
    assert story_service.get_story(session, story_id=story.id).state == (
        StoryState.IN_REVIEW
    )


def test_any_state_to_backlog_reset(session: Session) -> None:
    """
    Every non-backlog state allows a reset to backlog.
    """
    workspace_id = _make_workspace(session)

    # From todo.
    s1 = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="s1"),
    )
    session.commit()
    _advance(session, s1.id, StoryState.TODO)
    _advance(session, s1.id, StoryState.BACKLOG)
    assert story_service.get_story(session, story_id=s1.id).state == (
        StoryState.BACKLOG
    )

    # From in_progress.
    s2 = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="s2"),
    )
    session.commit()
    _advance(session, s2.id, StoryState.TODO)
    _advance(session, s2.id, StoryState.IN_PROGRESS)
    _advance(session, s2.id, StoryState.BACKLOG)
    assert story_service.get_story(session, story_id=s2.id).state == (
        StoryState.BACKLOG
    )

    # From done.
    s3 = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="s3"),
    )
    session.commit()
    for state in [
        StoryState.TODO,
        StoryState.IN_PROGRESS,
        StoryState.IN_REVIEW,
        StoryState.DONE,
    ]:
        _advance(session, s3.id, state)
    _advance(session, s3.id, StoryState.BACKLOG)
    assert story_service.get_story(session, story_id=s3.id).state == (
        StoryState.BACKLOG
    )


@pytest.mark.parametrize(
    ("preload", "bad_target"),
    [
        ([], StoryState.IN_REVIEW),  # backlog -> in_review
        ([StoryState.TODO], StoryState.DONE),  # todo -> done
        ([], StoryState.DONE),  # backlog -> done
        (
            [StoryState.TODO, StoryState.IN_PROGRESS, StoryState.IN_REVIEW],
            StoryState.TODO,
        ),  # in_review -> todo (not allowed)
    ],
)
def test_invalid_transitions_are_rejected(
    session: Session,
    preload: list[StoryState],
    bad_target: StoryState,
) -> None:
    """
    Representative invalid transitions raise
    :class:`InvalidStateTransitionError` and do not emit a
    ``state_changed`` audit row for the failed move.
    """
    workspace_id = _make_workspace(session)
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="s"),
    )
    session.commit()
    for state in preload:
        _advance(session, story.id, state)

    current = story_service.get_story(session, story_id=story.id)
    baseline_rows = _audit_rows(session, story.id)
    with pytest.raises(InvalidStateTransitionError):
        story_service.transition_story(
            session,
            actor=HUMAN,
            story_id=story.id,
            expected_version=current.version,
            to_state=bad_target,
        )
    session.rollback()
    assert len(_audit_rows(session, story.id)) == len(baseline_rows)


def test_no_op_transition_is_invalid(session: Session) -> None:
    """
    Transitioning to the current state has no legitimate meaning and
    is rejected as an invalid transition.
    """
    workspace_id = _make_workspace(session)
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="s"),
    )
    session.commit()

    with pytest.raises(InvalidStateTransitionError):
        story_service.transition_story(
            session,
            actor=HUMAN,
            story_id=story.id,
            expected_version=story.version,
            to_state=StoryState.BACKLOG,
        )


def test_transition_stale_version_rejected(session: Session) -> None:
    """
    A stale ``expected_version`` rejects the transition with
    :class:`VersionConflictError` before the state-machine check runs.
    """
    workspace_id = _make_workspace(session)
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="s"),
    )
    session.commit()
    with pytest.raises(VersionConflictError):
        story_service.transition_story(
            session,
            actor=HUMAN,
            story_id=story.id,
            expected_version=999,
            to_state=StoryState.TODO,
        )


def test_list_stories_filters_by_state_priority_and_epic(
    session: Session,
) -> None:
    """
    The combined filter surface returns only stories matching all
    supplied predicates.
    """
    workspace_id = _make_workspace(session)
    epic_id = _make_epic(session, workspace_id)

    # High priority in the epic, currently in_progress.
    high = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="h", priority=StoryPriority.HIGH, epic_id=epic_id),
    )
    session.commit()
    _advance(session, high.id, StoryState.TODO)
    _advance(session, high.id, StoryState.IN_PROGRESS)

    # Low priority, no epic, still backlog.
    story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="l", priority=StoryPriority.LOW),
    )
    session.commit()

    rows, _ = story_service.list_stories(
        session,
        workspace_id=workspace_id,
        state=StoryState.IN_PROGRESS,
        priority=StoryPriority.HIGH,
        epic_id=epic_id,
    )
    assert [s.id for s in rows] == [high.id]


def test_get_story_by_human_id_roundtrip(session: Session) -> None:
    """
    ``get_story_by_human_id`` finds a story by its ``KAN-N`` handle.
    """
    workspace_id = _make_workspace(session)
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=StoryCreate(title="s"),
    )
    session.commit()

    fetched = story_service.get_story_by_human_id(session, human_id=story.human_id)
    assert fetched.id == story.id


def test_get_story_by_unknown_human_id_raises(session: Session) -> None:
    """
    A human id that does not exist raises :class:`NotFoundError`.
    """
    with pytest.raises(NotFoundError):
        story_service.get_story_by_human_id(session, human_id="NOPE-1")
