"""
Direct tests for :func:`kanbaroo_core.services.audit.emit_audit`.

These cover the invariants the helper itself owns: diff shape,
JSON round-trip, UUID v7 PK generation, and ``occurred_at`` population.
Service-level tests in :mod:`test_services_workspaces` cover the
integration with actual mutations.
"""

import json

from sqlalchemy.orm import Session

from kanbaroo_core import Actor, ActorType
from kanbaroo_core.enums import AuditAction, AuditEntityType
from kanbaroo_core.models.audit import AuditEvent
from kanbaroo_core.services.audit import emit_audit


def test_emit_audit_creates_row_with_full_diff(session: Session) -> None:
    """
    ``emit_audit`` returns a populated row and the diff JSON round-trips
    with both halves intact.
    """
    actor = Actor(type=ActorType.HUMAN, id="adam")
    event = emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.WORKSPACE,
        entity_id="00000000-0000-0000-0000-000000000001",
        action=AuditAction.UPDATED,
        before={"name": "Old", "version": 1},
        after={"name": "New", "version": 2},
    )
    session.commit()

    assert event.id
    assert event.occurred_at.endswith("Z")
    assert event.actor_type == ActorType.HUMAN
    assert event.actor_id == "adam"
    assert event.action == "updated"

    payload = json.loads(event.diff)
    assert payload == {
        "before": {"name": "Old", "version": 1},
        "after": {"name": "New", "version": 2},
    }


def test_emit_audit_before_is_null_on_create(session: Session) -> None:
    """
    Create events have ``before=None``; the stored JSON preserves null.
    """
    actor = Actor(type=ActorType.CLAUDE, id="outer-claude")
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.WORKSPACE,
        entity_id="00000000-0000-0000-0000-000000000002",
        action=AuditAction.CREATED,
        before=None,
        after={"key": "KAN"},
    )
    session.commit()

    row = session.query(AuditEvent).one()
    payload = json.loads(row.diff)
    assert payload["before"] is None
    assert payload["after"] == {"key": "KAN"}


def test_emit_audit_accepts_plain_string_action(session: Session) -> None:
    """
    Plain strings are accepted alongside :class:`AuditAction` so future
    actions can be added without widening the enum in lockstep.
    """
    actor = Actor(type=ActorType.SYSTEM, id="migration-runner")
    event = emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.STORY,
        entity_id="00000000-0000-0000-0000-000000000003",
        action="auto_archived",
        before={"state": "done"},
        after={"state": "done", "deleted_at": "2026-04-17T00:00:00Z"},
    )
    session.commit()

    assert event.action == "auto_archived"


def test_emit_audit_does_not_commit(session: Session) -> None:
    """
    The helper flushes but never commits; the caller's transaction owns
    the boundary. Rolling back the session drops the event row.
    """
    actor = Actor(type=ActorType.HUMAN, id="adam")
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.WORKSPACE,
        entity_id="00000000-0000-0000-0000-000000000004",
        action=AuditAction.CREATED,
        before=None,
        after={},
    )
    session.rollback()

    assert session.query(AuditEvent).count() == 0
