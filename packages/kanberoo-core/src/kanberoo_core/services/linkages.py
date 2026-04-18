"""
Linkage CRUD service.

A linkage is a typed, directed relationship between two issues (story
or epic). Per ``docs/spec.md`` section 3.1, both the
``blocks``/``is_blocked_by`` and ``duplicates``/``is_duplicated_by``
pairs are automatically mirrored by this service: creating one end
atomically creates the matching row on the other side, and deleting
either end soft-deletes its mirror.

``relates_to`` is left unidirectional: it has no paired opposite, so
it is stored exactly as the caller supplied it and clients query both
``source`` and ``target`` to see related issues in either direction.

Cross-workspace linkages are allowed per spec §10 Q2. Both endpoints
must exist and be live; self-linkage is rejected; duplicate endpoints
with the same ``link_type`` are rejected (idempotency is not
desirable, per the cage E brief).

Linkages do not carry a ``version`` column, so there is no
``If-Match`` check on create or delete. The soft-delete is idempotent:
deleting an already-deleted linkage is a no-op and does not emit.

Audit contract: every ``create_linkage`` emits exactly one ``created``
row for the forward linkage. The mirror row (when one exists) does
**not** get its own audit event. ``delete_linkage`` likewise emits
exactly one ``soft_deleted`` row for the forward end; the mirror
cascade is an implementation detail.

Event contract: every ``create_linkage`` publishes exactly one
``{source_type}.linked`` event (``story.linked`` when the source is a
story, ``epic.linked`` when the source is an epic). ``delete_linkage``
publishes the matching ``{source_type}.unlinked`` event. The mirror
row is silent on the event stream for the same reason it is silent in
the audit log: a single logical linkage yields a single logical event.
"""

from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from kanberoo_core.actor import Actor
from kanberoo_core.enums import (
    AuditAction,
    AuditEntityType,
    LinkEndpointType,
    LinkType,
)
from kanberoo_core.models.epic import Epic
from kanberoo_core.models.linkage import Linkage
from kanberoo_core.models.story import Story
from kanberoo_core.queries import live
from kanberoo_core.schemas.linkage import LinkageCreate, LinkageRead
from kanberoo_core.services.audit import emit_audit
from kanberoo_core.services.events import publish_event
from kanberoo_core.services.exceptions import (
    NotFoundError,
    ValidationError,
)
from kanberoo_core.time import utc_now_iso

_MIRROR: dict[LinkType, LinkType] = {
    LinkType.BLOCKS: LinkType.IS_BLOCKED_BY,
    LinkType.IS_BLOCKED_BY: LinkType.BLOCKS,
    LinkType.DUPLICATES: LinkType.IS_DUPLICATED_BY,
    LinkType.IS_DUPLICATED_BY: LinkType.DUPLICATES,
}


def _dump(linkage: Linkage) -> dict[str, Any]:
    """
    Serialise a :class:`Linkage` row into a JSON-friendly dict for the
    audit log.
    """
    return LinkageRead.model_validate(linkage).model_dump(mode="json")


def _verify_endpoint_live(
    session: Session,
    *,
    endpoint_type: LinkEndpointType,
    endpoint_id: str,
    field: str,
) -> None:
    """
    Confirm that an endpoint (story or epic) exists and is not
    soft-deleted. Raises :class:`ValidationError` on either failure;
    the API layer surfaces it as a 400.
    """
    endpoint_type_value = (
        endpoint_type.value
        if isinstance(endpoint_type, LinkEndpointType)
        else endpoint_type
    )
    row: Story | Epic | None
    if endpoint_type_value == LinkEndpointType.STORY.value:
        row = session.get(Story, endpoint_id)
    elif endpoint_type_value == LinkEndpointType.EPIC.value:
        row = session.get(Epic, endpoint_id)
    else:
        raise ValidationError(field, f"unknown endpoint type {endpoint_type_value!r}")

    if row is None or row.deleted_at is not None:
        raise ValidationError(
            field,
            f"{endpoint_type_value} {endpoint_id!r} not found",
        )


def _find_linkage(
    session: Session,
    *,
    source_type: LinkEndpointType | str,
    source_id: str,
    target_type: LinkEndpointType | str,
    target_id: str,
    link_type: LinkType | str,
    include_deleted: bool = False,
) -> Linkage | None:
    """
    Look up a linkage by its natural key, optionally including
    soft-deleted rows.
    """
    stmt = select(Linkage).where(
        Linkage.source_type == source_type,
        Linkage.source_id == source_id,
        Linkage.target_type == target_type,
        Linkage.target_id == target_id,
        Linkage.link_type == link_type,
    )
    if not include_deleted:
        stmt = live(stmt, Linkage)
    return session.execute(stmt).scalar_one_or_none()


def create_linkage(
    session: Session,
    *,
    actor: Actor,
    payload: LinkageCreate,
) -> Linkage:
    """
    Create a linkage (and, for blocking or duplication pairs, its
    mirror) and emit a single ``created`` audit row.

    Validation:

    * Both endpoints must exist and be live. Either failure yields
      :class:`ValidationError`.
    * Self-linkage (``source == target``) is rejected.
    * A duplicate (same source/target/link_type) is rejected; creating
      "the same" linkage twice is treated as a client bug, not an
      idempotent no-op.

    For ``blocks``/``is_blocked_by`` and ``duplicates``/
    ``is_duplicated_by``, the mirror row is inserted atomically in the
    same transaction. Clients see a single logical linkage; the mirror
    is invisible except by direct table read. ``relates_to`` has no
    paired opposite and is left unidirectional.
    """
    _verify_endpoint_live(
        session,
        endpoint_type=payload.source_type,
        endpoint_id=payload.source_id,
        field="source_id",
    )
    _verify_endpoint_live(
        session,
        endpoint_type=payload.target_type,
        endpoint_id=payload.target_id,
        field="target_id",
    )

    source_type_value = (
        payload.source_type.value
        if isinstance(payload.source_type, LinkEndpointType)
        else payload.source_type
    )
    target_type_value = (
        payload.target_type.value
        if isinstance(payload.target_type, LinkEndpointType)
        else payload.target_type
    )
    link_type_value = (
        payload.link_type.value
        if isinstance(payload.link_type, LinkType)
        else payload.link_type
    )

    if (
        source_type_value == target_type_value
        and payload.source_id == payload.target_id
    ):
        raise ValidationError(
            "target_id",
            "source and target cannot be the same entity",
        )

    existing = _find_linkage(
        session,
        source_type=source_type_value,
        source_id=payload.source_id,
        target_type=target_type_value,
        target_id=payload.target_id,
        link_type=link_type_value,
        include_deleted=True,
    )
    if existing is not None and existing.deleted_at is None:
        raise ValidationError(
            "link_type",
            "a linkage with these endpoints and type already exists",
        )

    now = utc_now_iso()
    forward = Linkage(
        source_type=source_type_value,
        source_id=payload.source_id,
        target_type=target_type_value,
        target_id=payload.target_id,
        link_type=link_type_value,
        created_at=now,
    )
    session.add(forward)

    mirror_type = _MIRROR.get(LinkType(link_type_value))
    if mirror_type is not None:
        # Resurrect or create the mirror row. If it was previously
        # soft-deleted we clear ``deleted_at`` so the pair is
        # consistently live, rather than inserting a duplicate that
        # would violate the UNIQUE constraint.
        mirror_existing = _find_linkage(
            session,
            source_type=target_type_value,
            source_id=payload.target_id,
            target_type=source_type_value,
            target_id=payload.source_id,
            link_type=mirror_type.value,
            include_deleted=True,
        )
        if mirror_existing is None:
            mirror = Linkage(
                source_type=target_type_value,
                source_id=payload.target_id,
                target_type=source_type_value,
                target_id=payload.source_id,
                link_type=mirror_type.value,
                created_at=now,
            )
            session.add(mirror)
        elif mirror_existing.deleted_at is not None:
            mirror_existing.deleted_at = None

    session.flush()

    after = _dump(forward)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.LINKAGE,
        entity_id=forward.id,
        action=AuditAction.CREATED,
        before=None,
        after=after,
    )
    publish_event(
        session,
        event_type=f"{source_type_value}.linked",
        actor=actor,
        entity_type=AuditEntityType.LINKAGE.value,
        entity_id=forward.id,
        entity_version=None,
        payload=after,
    )
    return forward


def list_linkages_for_story(
    session: Session,
    *,
    story_id: str,
    include_deleted: bool = False,
) -> list[Linkage]:
    """
    Return every linkage whose source or target is ``story_id``.

    Merges incoming and outgoing so a single REST call can render both
    directions. Callers distinguish the two by comparing ``source_id``
    and ``target_id`` against the story id. Ordering is by
    ``created_at`` (then ``id`` as a tie-breaker) so the view stays
    stable.
    """
    story_endpoint = LinkEndpointType.STORY.value
    stmt = (
        select(Linkage)
        .where(
            or_(
                and_(
                    Linkage.source_type == story_endpoint,
                    Linkage.source_id == story_id,
                ),
                and_(
                    Linkage.target_type == story_endpoint,
                    Linkage.target_id == story_id,
                ),
            )
        )
        .order_by(Linkage.created_at, Linkage.id)
    )
    if not include_deleted:
        stmt = live(stmt, Linkage)
    return list(session.execute(stmt).scalars().all())


def get_linkage(
    session: Session,
    *,
    linkage_id: str,
    include_deleted: bool = False,
) -> Linkage:
    """
    Return a linkage by id or raise :class:`NotFoundError`.
    """
    linkage = session.get(Linkage, linkage_id)
    if linkage is None:
        raise NotFoundError("linkage", linkage_id)
    if linkage.deleted_at is not None and not include_deleted:
        raise NotFoundError("linkage", linkage_id)
    return linkage


def delete_linkage(
    session: Session,
    *,
    actor: Actor,
    linkage_id: str,
) -> None:
    """
    Soft-delete a linkage and its mirror, if any.

    Idempotent: if the linkage is already soft-deleted, returns without
    emitting an audit row. Otherwise stamps ``deleted_at`` on the
    forward row; if the link type is in :data:`_MIRROR`, the mirror
    row (looked up by swapped endpoints) is soft-deleted in the same
    transaction. Exactly one ``soft_deleted`` audit row is emitted,
    attributed to the forward linkage.
    """
    linkage = session.get(Linkage, linkage_id)
    if linkage is None:
        raise NotFoundError("linkage", linkage_id)
    if linkage.deleted_at is not None:
        return

    before = _dump(linkage)
    now = utc_now_iso()
    linkage.deleted_at = now

    mirror_type = _MIRROR.get(LinkType(linkage.link_type))
    if mirror_type is not None:
        mirror = _find_linkage(
            session,
            source_type=linkage.target_type,
            source_id=linkage.target_id,
            target_type=linkage.source_type,
            target_id=linkage.source_id,
            link_type=mirror_type.value,
        )
        if mirror is not None:
            mirror.deleted_at = now

    session.flush()

    after = _dump(linkage)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.LINKAGE,
        entity_id=linkage.id,
        action=AuditAction.SOFT_DELETED,
        before=before,
        after=after,
    )
    publish_event(
        session,
        event_type=f"{linkage.source_type}.unlinked",
        actor=actor,
        entity_type=AuditEntityType.LINKAGE.value,
        entity_id=linkage.id,
        entity_version=None,
        payload=after,
    )
    return None
