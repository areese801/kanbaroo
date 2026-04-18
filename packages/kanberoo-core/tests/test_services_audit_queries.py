"""
Tests for :func:`kanberoo_core.services.audit.list_audit` and
:func:`kanberoo_core.services.audit.list_audit_for_entity`.

Covers filter combinations, ``since`` cutoffs, cursor pagination, and
the per-entity convenience wrapper.
"""

import pytest
from sqlalchemy.orm import Session

from kanberoo_core import Actor, ActorType
from kanberoo_core.enums import AuditAction, AuditEntityType
from kanberoo_core.services.audit import (
    emit_audit,
    list_audit,
    list_audit_for_entity,
)
from kanberoo_core.services.exceptions import ValidationError

HUMAN = Actor(type=ActorType.HUMAN, id="adam")
CLAUDE = Actor(type=ActorType.CLAUDE, id="outer-claude")


def _emit_many(session: Session, count: int) -> list[str]:
    """
    Emit ``count`` audit rows alternating between two entity ids so
    the test can exercise filters and pagination without fighting
    timestamp collisions.
    """
    ids: list[str] = []
    for i in range(count):
        entity_id = f"entity-{i % 3}"
        actor = HUMAN if i % 2 == 0 else CLAUDE
        event = emit_audit(
            session,
            actor=actor,
            entity_type=AuditEntityType.STORY,
            entity_id=entity_id,
            action=AuditAction.UPDATED,
            before={"i": i - 1},
            after={"i": i},
        )
        ids.append(event.id)
    session.commit()
    return ids


def test_list_audit_returns_newest_first(session: Session) -> None:
    """
    Without filters, rows are returned ordered by ``occurred_at``
    descending, with ``id`` breaking ties.
    """
    _emit_many(session, 10)
    rows, cursor = list_audit(session, limit=5)
    assert len(rows) == 5
    assert cursor is not None
    # Ordering: non-increasing occurred_at.
    occurred = [row.occurred_at for row in rows]
    assert occurred == sorted(occurred, reverse=True)


def test_list_audit_filters_by_entity(session: Session) -> None:
    """
    ``entity_id`` and ``entity_type`` filters compose with AND.
    """
    _emit_many(session, 9)
    rows, _ = list_audit(
        session,
        entity_type=AuditEntityType.STORY,
        entity_id="entity-1",
        limit=50,
    )
    assert {row.entity_id for row in rows} == {"entity-1"}
    assert all(row.entity_type == AuditEntityType.STORY for row in rows)


def test_list_audit_filters_by_actor(session: Session) -> None:
    """
    ``actor_type`` and ``actor_id`` filters narrow to a single actor.
    """
    _emit_many(session, 6)
    rows, _ = list_audit(
        session,
        actor_type=ActorType.CLAUDE,
        actor_id="outer-claude",
        limit=50,
    )
    assert all(row.actor_id == "outer-claude" for row in rows)
    assert all(row.actor_type == ActorType.CLAUDE for row in rows)


def test_list_audit_cursor_walks_every_row(session: Session) -> None:
    """
    Following the cursor emitted by each page walks the full list
    without duplicates and terminates with ``next_cursor=None``.
    """
    _emit_many(session, 150)
    seen: list[str] = []
    cursor: str | None = None
    while True:
        rows, cursor = list_audit(session, limit=50, cursor=cursor)
        seen.extend(row.id for row in rows)
        if cursor is None:
            break
    assert len(seen) == 150
    assert len(set(seen)) == 150


def test_list_audit_since_skips_older_rows(session: Session) -> None:
    """
    ``since`` returns only rows strictly newer than the supplied
    timestamp.
    """
    ids = _emit_many(session, 5)
    first_row = session.get(
        __import__("kanberoo_core.models.audit", fromlist=["AuditEvent"]).AuditEvent,
        ids[0],
    )
    assert first_row is not None
    rows, _ = list_audit(session, since=first_row.occurred_at, limit=50)
    # Strict-inequality filter drops at least one row.
    assert len(rows) < 5


def test_list_audit_unknown_entity_type_raises(session: Session) -> None:
    """
    The service raises ``ValidationError`` for an unknown
    ``entity_type`` string so the API layer renders a 400.
    """
    with pytest.raises(ValidationError):
        list_audit(session, entity_type="not-a-type")


def test_list_audit_malformed_cursor_raises(session: Session) -> None:
    """
    A malformed cursor is rejected with a clean ``ValidationError``
    so clients get a 400 instead of an internal traceback.
    """
    with pytest.raises(ValidationError):
        list_audit(session, cursor="not-base64!")


def test_list_audit_for_entity_scoped_to_id(session: Session) -> None:
    """
    The convenience wrapper returns only rows for the requested entity.
    """
    _emit_many(session, 9)
    rows, _ = list_audit_for_entity(
        session,
        entity_type=AuditEntityType.STORY,
        entity_id="entity-2",
        limit=50,
    )
    assert {row.entity_id for row in rows} == {"entity-2"}
