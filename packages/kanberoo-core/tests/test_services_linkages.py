"""
Service-layer tests for linkages.

Covers: automatic ``blocks`` ↔ ``is_blocked_by`` mirroring (and the
deliberate non-mirroring of ``duplicates``/``relates_to``),
self-linkage rejection, duplicate rejection, cross-workspace linking
allowed, and the audit invariant that exactly one ``created`` /
``soft_deleted`` row is emitted for the forward linkage while the
mirror is silent.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from kanberoo_core import Actor, ActorType, LinkEndpointType, LinkType
from kanberoo_core.enums import AuditEntityType
from kanberoo_core.models.audit import AuditEvent
from kanberoo_core.models.linkage import Linkage
from kanberoo_core.schemas.linkage import LinkageCreate
from kanberoo_core.schemas.story import StoryCreate
from kanberoo_core.schemas.workspace import WorkspaceCreate
from kanberoo_core.services import linkages as linkage_service
from kanberoo_core.services import stories as story_service
from kanberoo_core.services import workspaces as ws_service
from kanberoo_core.services.exceptions import (
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


def _two_stories(session: Session, *, same_workspace: bool = True) -> tuple[str, str]:
    """
    Create two stories and return their ids. ``same_workspace`` is
    ``False`` to exercise cross-workspace linkages.
    """
    ws_a = ws_service.create_workspace(
        session, actor=HUMAN, payload=WorkspaceCreate(key="AAA", name="a")
    )
    session.commit()
    story_a = story_service.create_story(
        session, actor=HUMAN, workspace_id=ws_a.id, payload=StoryCreate(title="a")
    )
    session.commit()

    if same_workspace:
        story_b = story_service.create_story(
            session, actor=HUMAN, workspace_id=ws_a.id, payload=StoryCreate(title="b")
        )
    else:
        ws_b = ws_service.create_workspace(
            session, actor=HUMAN, payload=WorkspaceCreate(key="BBB", name="b")
        )
        session.commit()
        story_b = story_service.create_story(
            session, actor=HUMAN, workspace_id=ws_b.id, payload=StoryCreate(title="b")
        )
    session.commit()
    return story_a.id, story_b.id


def _all_linkages(session: Session, include_deleted: bool = True) -> list[Linkage]:
    """
    Return every linkage row for debugging / invariant checking.
    """
    return list(session.execute(select(Linkage)).scalars().all())


def test_blocks_creates_mirror_atomically(session: Session) -> None:
    """
    Creating a ``blocks`` linkage atomically writes the
    ``is_blocked_by`` mirror on the other endpoint.
    """
    a, b = _two_stories(session)
    forward = linkage_service.create_linkage(
        session,
        actor=HUMAN,
        payload=LinkageCreate(
            source_type=LinkEndpointType.STORY,
            source_id=a,
            target_type=LinkEndpointType.STORY,
            target_id=b,
            link_type=LinkType.BLOCKS,
        ),
    )
    session.commit()

    rows = _all_linkages(session, include_deleted=True)
    assert len(rows) == 2
    by_type = {r.link_type: r for r in rows}
    assert LinkType.BLOCKS in by_type and LinkType.IS_BLOCKED_BY in by_type
    mirror = by_type[LinkType.IS_BLOCKED_BY]
    assert mirror.source_id == b and mirror.target_id == a
    assert forward.link_type == LinkType.BLOCKS


def test_blocks_emits_single_audit_for_forward(session: Session) -> None:
    """
    Only the forward linkage emits a ``created`` audit row; the mirror
    is silent.
    """
    a, b = _two_stories(session)
    forward = linkage_service.create_linkage(
        session,
        actor=HUMAN,
        payload=LinkageCreate(
            source_type=LinkEndpointType.STORY,
            source_id=a,
            target_type=LinkEndpointType.STORY,
            target_id=b,
            link_type=LinkType.BLOCKS,
        ),
    )
    session.commit()

    linkage_events = (
        session.query(AuditEvent)
        .filter(AuditEvent.entity_type == AuditEntityType.LINKAGE)
        .all()
    )
    assert len(linkage_events) == 1
    assert linkage_events[0].entity_id == forward.id
    assert linkage_events[0].action == "created"


def test_relates_to_is_not_mirrored(session: Session) -> None:
    """
    ``relates_to`` is left unidirectional; no mirror row is created.
    """
    a, b = _two_stories(session)
    linkage_service.create_linkage(
        session,
        actor=HUMAN,
        payload=LinkageCreate(
            source_type=LinkEndpointType.STORY,
            source_id=a,
            target_type=LinkEndpointType.STORY,
            target_id=b,
            link_type=LinkType.RELATES_TO,
        ),
    )
    session.commit()
    assert len(_all_linkages(session)) == 1


def test_duplicates_is_not_mirrored(session: Session) -> None:
    """
    ``duplicates`` is left unidirectional; no
    ``is_duplicated_by`` is auto-created.
    """
    a, b = _two_stories(session)
    linkage_service.create_linkage(
        session,
        actor=HUMAN,
        payload=LinkageCreate(
            source_type=LinkEndpointType.STORY,
            source_id=a,
            target_type=LinkEndpointType.STORY,
            target_id=b,
            link_type=LinkType.DUPLICATES,
        ),
    )
    session.commit()
    rows = _all_linkages(session)
    assert len(rows) == 1
    assert rows[0].link_type == LinkType.DUPLICATES


def test_self_linkage_rejected(session: Session) -> None:
    """
    A linkage whose source and target are the same entity is rejected.
    """
    a, _ = _two_stories(session)
    with pytest.raises(ValidationError):
        linkage_service.create_linkage(
            session,
            actor=HUMAN,
            payload=LinkageCreate(
                source_type=LinkEndpointType.STORY,
                source_id=a,
                target_type=LinkEndpointType.STORY,
                target_id=a,
                link_type=LinkType.RELATES_TO,
            ),
        )


def test_duplicate_linkage_rejected(session: Session) -> None:
    """
    Creating the same linkage (same source, target, link_type) twice
    is rejected with :class:`ValidationError`.
    """
    a, b = _two_stories(session)
    linkage_service.create_linkage(
        session,
        actor=HUMAN,
        payload=LinkageCreate(
            source_type=LinkEndpointType.STORY,
            source_id=a,
            target_type=LinkEndpointType.STORY,
            target_id=b,
            link_type=LinkType.RELATES_TO,
        ),
    )
    session.commit()

    with pytest.raises(ValidationError):
        linkage_service.create_linkage(
            session,
            actor=HUMAN,
            payload=LinkageCreate(
                source_type=LinkEndpointType.STORY,
                source_id=a,
                target_type=LinkEndpointType.STORY,
                target_id=b,
                link_type=LinkType.RELATES_TO,
            ),
        )


def test_cross_workspace_linkage_allowed(session: Session) -> None:
    """
    Per spec §10 Q2, linkages across workspaces are allowed.
    """
    a, b = _two_stories(session, same_workspace=False)
    linkage_service.create_linkage(
        session,
        actor=HUMAN,
        payload=LinkageCreate(
            source_type=LinkEndpointType.STORY,
            source_id=a,
            target_type=LinkEndpointType.STORY,
            target_id=b,
            link_type=LinkType.RELATES_TO,
        ),
    )
    session.commit()
    assert len(_all_linkages(session)) == 1


def test_list_linkages_for_story_unifies_in_and_out(session: Session) -> None:
    """
    ``list_linkages_for_story`` returns both incoming and outgoing
    linkages for a given story (including the mirror side of a blocks
    pair).
    """
    a, b = _two_stories(session)
    linkage_service.create_linkage(
        session,
        actor=HUMAN,
        payload=LinkageCreate(
            source_type=LinkEndpointType.STORY,
            source_id=a,
            target_type=LinkEndpointType.STORY,
            target_id=b,
            link_type=LinkType.BLOCKS,
        ),
    )
    session.commit()

    # Story a sees: a blocks b (outgoing) + b is_blocked_by a (incoming mirror).
    a_linkages = linkage_service.list_linkages_for_story(session, story_id=a)
    # Story b sees: a blocks b (incoming) + b is_blocked_by a (outgoing mirror).
    b_linkages = linkage_service.list_linkages_for_story(session, story_id=b)

    # Both ends see both rows; the caller tells direction by comparing
    # source_id / target_id against the story id.
    assert len(a_linkages) == 2
    assert len(b_linkages) == 2
    a_outgoing = [li for li in a_linkages if li.source_id == a]
    a_incoming = [li for li in a_linkages if li.target_id == a]
    assert len(a_outgoing) == 1 and a_outgoing[0].link_type == LinkType.BLOCKS
    assert len(a_incoming) == 1 and a_incoming[0].link_type == LinkType.IS_BLOCKED_BY
    types = {li.link_type for li in b_linkages}
    assert types == {LinkType.BLOCKS, LinkType.IS_BLOCKED_BY}


def test_delete_cascades_to_mirror_for_blocks_pair(session: Session) -> None:
    """
    Deleting one side of a blocks pair soft-deletes both rows and
    emits exactly one audit row on the forward.
    """
    a, b = _two_stories(session)
    forward = linkage_service.create_linkage(
        session,
        actor=HUMAN,
        payload=LinkageCreate(
            source_type=LinkEndpointType.STORY,
            source_id=a,
            target_type=LinkEndpointType.STORY,
            target_id=b,
            link_type=LinkType.BLOCKS,
        ),
    )
    session.commit()

    linkage_service.delete_linkage(session, actor=HUMAN, linkage_id=forward.id)
    session.commit()

    rows = _all_linkages(session, include_deleted=True)
    assert len(rows) == 2
    for r in rows:
        assert r.deleted_at is not None

    linkage_events = (
        session.query(AuditEvent)
        .filter(AuditEvent.entity_type == AuditEntityType.LINKAGE)
        .order_by(AuditEvent.occurred_at)
        .all()
    )
    actions = [e.action for e in linkage_events]
    assert actions == ["created", "soft_deleted"]
    # Both events are attributed to the forward id, not the mirror.
    assert all(e.entity_id == forward.id for e in linkage_events)


def test_delete_idempotent_on_already_deleted(session: Session) -> None:
    """
    Deleting an already-soft-deleted linkage is a silent no-op and
    does not emit a second audit row.
    """
    a, b = _two_stories(session)
    link = linkage_service.create_linkage(
        session,
        actor=HUMAN,
        payload=LinkageCreate(
            source_type=LinkEndpointType.STORY,
            source_id=a,
            target_type=LinkEndpointType.STORY,
            target_id=b,
            link_type=LinkType.RELATES_TO,
        ),
    )
    session.commit()
    linkage_service.delete_linkage(session, actor=HUMAN, linkage_id=link.id)
    session.commit()
    linkage_service.delete_linkage(session, actor=HUMAN, linkage_id=link.id)
    session.commit()

    linkage_events = (
        session.query(AuditEvent).filter(AuditEvent.entity_id == link.id).all()
    )
    actions = [e.action for e in linkage_events]
    assert actions == ["created", "soft_deleted"]


def test_delete_unknown_linkage_raises(session: Session) -> None:
    """
    Deleting an unknown id raises :class:`NotFoundError`.
    """
    with pytest.raises(NotFoundError):
        linkage_service.delete_linkage(session, actor=HUMAN, linkage_id="missing")


def test_create_linkage_soft_deleted_endpoint_rejected(session: Session) -> None:
    """
    Creating a linkage whose source or target is soft-deleted is
    rejected with :class:`ValidationError`.
    """
    a, b = _two_stories(session)
    story_a = story_service.get_story(session, story_id=a)
    story_service.soft_delete_story(
        session,
        actor=HUMAN,
        story_id=a,
        expected_version=story_a.version,
    )
    session.commit()

    with pytest.raises(ValidationError):
        linkage_service.create_linkage(
            session,
            actor=HUMAN,
            payload=LinkageCreate(
                source_type=LinkEndpointType.STORY,
                source_id=a,
                target_type=LinkEndpointType.STORY,
                target_id=b,
                link_type=LinkType.RELATES_TO,
            ),
        )
