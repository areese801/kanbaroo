"""
Service-layer tests for workspaces.

These tests exercise the full CRUD flow through
:mod:`kanberoo_core.services.workspaces` and assert the load-bearing
invariant: every mutation writes an ``audit_events`` row attributed to
the correct actor, with the right entity and action. The negative case
(no audit on failed concurrency checks) is also covered.
"""

import json

import pytest
from sqlalchemy.orm import Session

from kanberoo_core import Actor, ActorType
from kanberoo_core.enums import AuditEntityType
from kanberoo_core.models.audit import AuditEvent
from kanberoo_core.models.workspace import Workspace
from kanberoo_core.schemas.workspace import WorkspaceCreate, WorkspaceUpdate
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


def test_create_workspace_emits_audit(session: Session) -> None:
    """
    Creating a workspace writes exactly one audit row tagged
    ``created`` with ``before=null``.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanberoo"),
    )
    session.commit()

    events = _audit_rows(session, workspace.id)
    assert len(events) == 1
    row = events[0]
    assert row.entity_type == AuditEntityType.WORKSPACE
    assert row.action == "created"
    assert row.actor_type == ActorType.HUMAN
    assert row.actor_id == "adam"

    diff = json.loads(row.diff)
    assert diff["before"] is None
    assert diff["after"]["key"] == "KAN"
    assert diff["after"]["version"] == 1


def test_create_workspace_rejects_duplicate_key(session: Session) -> None:
    """
    Duplicate ``key`` values raise :class:`ValidationError` before any
    INSERT and do not emit an audit row.
    """
    ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanberoo"),
    )
    session.commit()

    before_count = session.query(AuditEvent).count()
    with pytest.raises(ValidationError):
        ws_service.create_workspace(
            session,
            actor=HUMAN,
            payload=WorkspaceCreate(key="KAN", name="Other"),
        )
    session.rollback()
    assert session.query(AuditEvent).count() == before_count


def test_update_workspace_emits_audit_with_before_and_after(
    session: Session,
) -> None:
    """
    A successful update writes a second audit row containing both the
    pre-image and the post-image.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanberoo"),
    )
    session.commit()
    original_version = workspace.version

    updated = ws_service.update_workspace(
        session,
        actor=HUMAN,
        workspace_id=workspace.id,
        expected_version=original_version,
        payload=WorkspaceUpdate(name="Kanberoo Renamed"),
    )
    session.commit()

    assert updated.version == original_version + 1
    events = _audit_rows(session, workspace.id)
    assert [e.action for e in events] == ["created", "updated"]

    diff = json.loads(events[1].diff)
    assert diff["before"]["name"] == "Kanberoo"
    assert diff["after"]["name"] == "Kanberoo Renamed"
    assert diff["before"]["version"] == original_version
    assert diff["after"]["version"] == original_version + 1


def test_update_workspace_rejects_stale_version(session: Session) -> None:
    """
    ``expected_version`` mismatch raises :class:`VersionConflictError`
    and does not emit an audit row.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanberoo"),
    )
    session.commit()

    with pytest.raises(VersionConflictError):
        ws_service.update_workspace(
            session,
            actor=HUMAN,
            workspace_id=workspace.id,
            expected_version=999,
            payload=WorkspaceUpdate(name="Whatever"),
        )
    session.rollback()

    events = _audit_rows(session, workspace.id)
    assert [e.action for e in events] == ["created"]


def test_soft_delete_workspace_emits_audit_and_hides_from_get(
    session: Session,
) -> None:
    """
    Soft-delete stamps ``deleted_at``, emits an audit row, and hides the
    row from the default :func:`get_workspace` path.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanberoo"),
    )
    session.commit()

    ws_service.soft_delete_workspace(
        session,
        actor=HUMAN,
        workspace_id=workspace.id,
        expected_version=workspace.version,
    )
    session.commit()

    events = _audit_rows(session, workspace.id)
    assert [e.action for e in events] == ["created", "soft_deleted"]
    diff = json.loads(events[1].diff)
    assert diff["before"]["deleted_at"] is None
    assert diff["after"]["deleted_at"] is not None

    with pytest.raises(NotFoundError):
        ws_service.get_workspace(session, workspace_id=workspace.id)

    restored = ws_service.get_workspace(
        session,
        workspace_id=workspace.id,
        include_deleted=True,
    )
    assert restored.id == workspace.id


def test_list_workspaces_paginates_with_cursor(session: Session) -> None:
    """
    ``list_workspaces`` returns a page plus a cursor; following the
    cursor walks the remainder without duplicates.
    """
    created_ids: list[str] = []
    for i in range(25):
        ws = ws_service.create_workspace(
            session,
            actor=HUMAN,
            payload=WorkspaceCreate(key=f"WS{i:02d}", name=f"WS {i}"),
        )
        created_ids.append(ws.id)
    session.commit()

    page_one, cursor = ws_service.list_workspaces(session, limit=10)
    assert len(page_one) == 10
    assert cursor is not None

    page_two, cursor_two = ws_service.list_workspaces(session, limit=10, cursor=cursor)
    assert len(page_two) == 10
    assert cursor_two is not None

    page_three, cursor_three = ws_service.list_workspaces(
        session, limit=10, cursor=cursor_two
    )
    assert len(page_three) == 5
    assert cursor_three is None

    all_ids = [w.id for w in page_one + page_two + page_three]
    assert sorted(all_ids) == sorted(created_ids)


def test_list_workspaces_hides_soft_deleted_by_default(
    session: Session,
) -> None:
    """
    Default list calls skip soft-deleted rows; ``include_deleted=True``
    returns them.
    """
    live_ws = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="LIVE", name="Live"),
    )
    gone_ws = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="GONE", name="Gone"),
    )
    session.commit()
    ws_service.soft_delete_workspace(
        session,
        actor=HUMAN,
        workspace_id=gone_ws.id,
        expected_version=gone_ws.version,
    )
    session.commit()

    default_rows, _ = ws_service.list_workspaces(session)
    assert [w.id for w in default_rows] == [live_ws.id]

    all_rows, _ = ws_service.list_workspaces(session, include_deleted=True)
    assert {w.id for w in all_rows} == {live_ws.id, gone_ws.id}


def test_get_workspace_missing_raises_not_found(session: Session) -> None:
    """
    An unknown id raises :class:`NotFoundError`.
    """
    with pytest.raises(NotFoundError):
        ws_service.get_workspace(session, workspace_id="does-not-exist")


def test_audit_actor_attribution_varies(session: Session) -> None:
    """
    The ``actor`` parameter is the single source of truth for the row's
    ``actor_type`` / ``actor_id`` fields.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=Actor(type=ActorType.CLAUDE, id="outer-claude"),
        payload=WorkspaceCreate(key="KAN", name="Kanberoo"),
    )
    session.commit()
    ws_service.update_workspace(
        session,
        actor=Actor(type=ActorType.SYSTEM, id="migration"),
        workspace_id=workspace.id,
        expected_version=workspace.version,
        payload=WorkspaceUpdate(description="rename by system"),
    )
    session.commit()

    events = _audit_rows(session, workspace.id)
    assert [e.actor_type for e in events] == [ActorType.CLAUDE, ActorType.SYSTEM]
    assert [e.actor_id for e in events] == ["outer-claude", "migration"]


def test_get_workspace_by_key_is_case_insensitive(session: Session) -> None:
    """
    ``get_workspace_by_key`` matches ``KAN``, ``kan``, ``Kan``
    interchangeably so the REST layer is forgiving regardless of the
    client's casing habits.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanberoo"),
    )
    session.commit()

    for variant in ("KAN", "kan", "Kan"):
        fetched = ws_service.get_workspace_by_key(session, key=variant)
        assert fetched.id == workspace.id


def test_unique_constraint_smoke(session: Session) -> None:
    """
    Sanity-check that the create path inserts a real row (not just an
    audit event) so the optimistic concurrency tests have something to
    bite.
    """
    ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanberoo"),
    )
    session.commit()
    assert session.query(Workspace).count() == 1
