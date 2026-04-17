"""
Service-layer tests for epics.

These tests exercise :mod:`kanberoo_core.services.epics` end-to-end:
create, read, update, soft-delete, and the close/reopen convenience
wrappers. The load-bearing invariant asserted throughout is that every
successful mutation writes exactly one ``audit_events`` row attributed
to the correct actor with the expected action, and idempotent
close/reopen transitions do not emit a row when the state is already
the target.
"""

import json

import pytest
from sqlalchemy.orm import Session

from kanberoo_core import Actor, ActorType
from kanberoo_core.enums import AuditEntityType, EpicState
from kanberoo_core.models.audit import AuditEvent
from kanberoo_core.schemas.epic import EpicCreate, EpicUpdate
from kanberoo_core.schemas.workspace import WorkspaceCreate
from kanberoo_core.services import epics as epic_service
from kanberoo_core.services import workspaces as ws_service
from kanberoo_core.services.exceptions import (
    NotFoundError,
    ValidationError,
    VersionConflictError,
)

HUMAN = Actor(type=ActorType.HUMAN, id="adam")


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


def test_create_epic_emits_audit_and_allocates_human_id(session: Session) -> None:
    """
    Creating an epic emits a single ``created`` audit row and allocates
    the next workspace human id.
    """
    workspace_id = _make_workspace(session)
    epic = epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=EpicCreate(title="v1 release"),
    )
    session.commit()

    assert epic.human_id == "KAN-1"
    events = _audit_rows(session, epic.id)
    assert len(events) == 1
    row = events[0]
    assert row.entity_type == AuditEntityType.EPIC
    assert row.action == "created"
    assert row.actor_type == ActorType.HUMAN
    assert row.actor_id == "adam"

    diff = json.loads(row.diff)
    assert diff["before"] is None
    assert diff["after"]["human_id"] == "KAN-1"
    assert diff["after"]["state"] == "open"


def test_create_epic_unknown_workspace_raises_not_found(session: Session) -> None:
    """
    Attempting to create an epic in a non-existent workspace raises
    :class:`NotFoundError`.
    """
    with pytest.raises(NotFoundError):
        epic_service.create_epic(
            session,
            actor=HUMAN,
            workspace_id="nope",
            payload=EpicCreate(title="x"),
        )


def test_update_epic_emits_before_and_after_audit(session: Session) -> None:
    """
    Updating an epic writes an ``updated`` row carrying both pre- and
    post-image field values.
    """
    workspace_id = _make_workspace(session)
    epic = epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=EpicCreate(title="v1 release"),
    )
    session.commit()

    updated = epic_service.update_epic(
        session,
        actor=HUMAN,
        epic_id=epic.id,
        expected_version=epic.version,
        payload=EpicUpdate(title="v1.0 release", description="GA cut"),
    )
    session.commit()

    assert updated.title == "v1.0 release"
    assert updated.description == "GA cut"
    assert updated.version == 2

    events = _audit_rows(session, epic.id)
    assert [e.action for e in events] == ["created", "updated"]
    diff = json.loads(events[1].diff)
    assert diff["before"]["title"] == "v1 release"
    assert diff["after"]["title"] == "v1.0 release"
    assert diff["before"]["description"] is None
    assert diff["after"]["description"] == "GA cut"


def test_update_epic_stale_version_raises(session: Session) -> None:
    """
    A stale ``expected_version`` raises :class:`VersionConflictError`
    and emits no audit row.
    """
    workspace_id = _make_workspace(session)
    epic = epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=EpicCreate(title="v1"),
    )
    session.commit()

    with pytest.raises(VersionConflictError):
        epic_service.update_epic(
            session,
            actor=HUMAN,
            epic_id=epic.id,
            expected_version=999,
            payload=EpicUpdate(title="nope"),
        )
    session.rollback()
    assert [e.action for e in _audit_rows(session, epic.id)] == ["created"]


def test_soft_delete_epic_hides_from_get(session: Session) -> None:
    """
    Soft-delete stamps ``deleted_at``, emits an audit row, and hides
    the row from the default :func:`get_epic` path.
    """
    workspace_id = _make_workspace(session)
    epic = epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=EpicCreate(title="v1"),
    )
    session.commit()

    epic_service.soft_delete_epic(
        session,
        actor=HUMAN,
        epic_id=epic.id,
        expected_version=epic.version,
    )
    session.commit()

    events = _audit_rows(session, epic.id)
    assert [e.action for e in events] == ["created", "soft_deleted"]

    with pytest.raises(NotFoundError):
        epic_service.get_epic(session, epic_id=epic.id)
    restored = epic_service.get_epic(session, epic_id=epic.id, include_deleted=True)
    assert restored.id == epic.id


def test_close_epic_transitions_state_and_emits_audit(session: Session) -> None:
    """
    ``close_epic`` sets ``state`` to ``closed`` and writes an
    ``updated`` audit row.
    """
    workspace_id = _make_workspace(session)
    epic = epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=EpicCreate(title="v1"),
    )
    session.commit()

    closed = epic_service.close_epic(
        session,
        actor=HUMAN,
        epic_id=epic.id,
        expected_version=epic.version,
    )
    session.commit()

    assert closed.state == EpicState.CLOSED
    events = _audit_rows(session, epic.id)
    assert [e.action for e in events] == ["created", "updated"]
    diff = json.loads(events[1].diff)
    assert diff["before"]["state"] == "open"
    assert diff["after"]["state"] == "closed"


def test_close_epic_already_closed_is_idempotent_noop(session: Session) -> None:
    """
    Closing an already-closed epic returns the epic unchanged and does
    not emit a new audit row.
    """
    workspace_id = _make_workspace(session)
    epic = epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=EpicCreate(title="v1"),
    )
    session.commit()
    epic_service.close_epic(
        session,
        actor=HUMAN,
        epic_id=epic.id,
        expected_version=epic.version,
    )
    session.commit()
    version_after_close = epic.version

    result = epic_service.close_epic(
        session,
        actor=HUMAN,
        epic_id=epic.id,
        expected_version=version_after_close,
    )
    session.commit()

    assert result.state == EpicState.CLOSED
    assert result.version == version_after_close
    events = _audit_rows(session, epic.id)
    assert [e.action for e in events] == ["created", "updated"]


def test_reopen_epic_transitions_back_to_open(session: Session) -> None:
    """
    ``reopen_epic`` restores ``state=open`` and emits an ``updated``
    audit row.
    """
    workspace_id = _make_workspace(session)
    epic = epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=EpicCreate(title="v1"),
    )
    session.commit()
    epic_service.close_epic(
        session,
        actor=HUMAN,
        epic_id=epic.id,
        expected_version=epic.version,
    )
    session.commit()

    reopened = epic_service.reopen_epic(
        session,
        actor=HUMAN,
        epic_id=epic.id,
        expected_version=epic.version,
    )
    session.commit()

    assert reopened.state == EpicState.OPEN
    events = _audit_rows(session, epic.id)
    assert [e.action for e in events] == ["created", "updated", "updated"]


def test_reopen_already_open_is_noop(session: Session) -> None:
    """
    Reopening an already-open epic returns unchanged and emits no new
    audit row.
    """
    workspace_id = _make_workspace(session)
    epic = epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=EpicCreate(title="v1"),
    )
    session.commit()

    result = epic_service.reopen_epic(
        session,
        actor=HUMAN,
        epic_id=epic.id,
        expected_version=epic.version,
    )
    session.commit()

    assert result.state == EpicState.OPEN
    assert [e.action for e in _audit_rows(session, epic.id)] == ["created"]


def test_close_epic_stale_version_rejected(session: Session) -> None:
    """
    ``close_epic`` honours ``expected_version`` even when the
    transition would be a no-op, so a stale ``If-Match`` is rejected
    with :class:`VersionConflictError`.
    """
    workspace_id = _make_workspace(session)
    epic = epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=workspace_id,
        payload=EpicCreate(title="v1"),
    )
    session.commit()

    with pytest.raises(VersionConflictError):
        epic_service.close_epic(
            session,
            actor=HUMAN,
            epic_id=epic.id,
            expected_version=999,
        )


def test_list_epics_paginates_and_hides_soft_deleted(session: Session) -> None:
    """
    ``list_epics`` paginates by id cursor and skips soft-deleted rows
    by default.
    """
    workspace_id = _make_workspace(session)
    created_ids: list[str] = []
    for i in range(9):
        ep = epic_service.create_epic(
            session,
            actor=HUMAN,
            workspace_id=workspace_id,
            payload=EpicCreate(title=f"epic {i}"),
        )
        created_ids.append(ep.id)
    session.commit()

    # Soft-delete one so we can verify it's hidden; that leaves 8 live
    # which paginates to 3 + 3 + 2 under a limit of 3.
    to_delete = created_ids[0]
    original = epic_service.get_epic(session, epic_id=to_delete)
    epic_service.soft_delete_epic(
        session,
        actor=HUMAN,
        epic_id=to_delete,
        expected_version=original.version,
    )
    session.commit()

    first, cursor = epic_service.list_epics(session, workspace_id=workspace_id, limit=3)
    assert len(first) == 3
    assert to_delete not in [e.id for e in first]

    second, cursor2 = epic_service.list_epics(
        session, workspace_id=workspace_id, limit=3, cursor=cursor
    )
    assert len(second) == 3
    assert cursor2 is not None

    third, cursor3 = epic_service.list_epics(
        session, workspace_id=workspace_id, limit=3, cursor=cursor2
    )
    assert len(third) == 2
    assert cursor3 is None

    with_deleted, _ = epic_service.list_epics(
        session,
        workspace_id=workspace_id,
        limit=50,
        include_deleted=True,
    )
    assert to_delete in [e.id for e in with_deleted]


def test_list_epics_scoped_to_workspace(session: Session) -> None:
    """
    ``list_epics`` only returns epics from the requested workspace.
    """
    ws_a = _make_workspace(session, key="AAA")
    ws_b = _make_workspace(session, key="BBB")
    epic_service.create_epic(
        session, actor=HUMAN, workspace_id=ws_a, payload=EpicCreate(title="a")
    )
    epic_service.create_epic(
        session, actor=HUMAN, workspace_id=ws_b, payload=EpicCreate(title="b")
    )
    session.commit()

    a_rows, _ = epic_service.list_epics(session, workspace_id=ws_a)
    b_rows, _ = epic_service.list_epics(session, workspace_id=ws_b)
    assert {e.workspace_id for e in a_rows} == {ws_a}
    assert {e.workspace_id for e in b_rows} == {ws_b}


def test_update_unknown_epic_is_not_found(session: Session) -> None:
    """
    Patching an unknown id raises :class:`NotFoundError`.
    """
    with pytest.raises(NotFoundError):
        epic_service.update_epic(
            session,
            actor=HUMAN,
            epic_id="does-not-exist",
            expected_version=1,
            payload=EpicUpdate(title="x"),
        )


def test_get_epic_with_invalid_cursor_raises_validation(session: Session) -> None:
    """
    A malformed cursor translates to a :class:`ValidationError`.
    """
    workspace_id = _make_workspace(session)
    with pytest.raises(ValidationError):
        epic_service.list_epics(
            session,
            workspace_id=workspace_id,
            cursor="!!!not-base64!!!",
        )
