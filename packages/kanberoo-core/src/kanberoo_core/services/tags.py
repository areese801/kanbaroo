"""
Tag CRUD and story-association service.

Tags are workspace-scoped labels. A tag named ``bug`` in workspace A is
a distinct row from ``bug`` in workspace B; the ``UNIQUE (workspace_id,
name)`` constraint enforces that at the schema level.

Tags diverge from the other mutable resources: the spec schema in
``docs/spec.md`` section 3.3 does **not** give tags a ``version`` or
``updated_at`` column, so optimistic concurrency does not apply. Tag
updates and soft-deletes therefore do not require ``If-Match``.

Soft-deleting a tag also **detaches it from every story** (deletes all
``story_tags`` rows referencing the tag) in the same transaction,
per ``docs/spec.md`` section 4.2 ("Soft delete (detaches from
stories)"). Only a single ``soft_deleted`` audit row is emitted for the
tag itself; the story-side cleanup is treated as an implementation
detail and does not emit per-row audit events.

Tag add/remove on a story does emit one audit row per tag change,
attributed against the story (``entity_type="story"``,
``action="tag_added"|"tag_removed"``). Rationale: from a client's
perspective tagging is a change to the story, so the story's audit
trail is where an observer should look.
"""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from kanberoo_core.actor import Actor
from kanberoo_core.enums import AuditAction, AuditEntityType
from kanberoo_core.models.story import Story
from kanberoo_core.models.story_tag import story_tags
from kanberoo_core.models.tag import Tag
from kanberoo_core.queries import live
from kanberoo_core.schemas.tag import TagCreate, TagRead, TagUpdate
from kanberoo_core.services.audit import emit_audit
from kanberoo_core.services.events import publish_event
from kanberoo_core.services.exceptions import (
    NotFoundError,
    ValidationError,
)
from kanberoo_core.text import normalize_for_comparison
from kanberoo_core.time import utc_now_iso


def _dump(tag: Tag) -> dict[str, Any]:
    """
    Serialise a :class:`Tag` row into a JSON-friendly dict for the
    audit log.
    """
    return TagRead.model_validate(tag).model_dump(mode="json")


def _get_live_story(session: Session, story_id: str) -> Story:
    """
    Return a live story by id or raise :class:`NotFoundError`.
    """
    story = session.get(Story, story_id)
    if story is None or story.deleted_at is not None:
        raise NotFoundError("story", story_id)
    return story


def _get_live_tag(session: Session, tag_id: str) -> Tag:
    """
    Return a live tag by id or raise :class:`NotFoundError`.
    """
    tag = session.get(Tag, tag_id)
    if tag is None or tag.deleted_at is not None:
        raise NotFoundError("tag", tag_id)
    return tag


def create_tag(
    session: Session,
    *,
    actor: Actor,
    workspace_id: str,
    payload: TagCreate,
) -> Tag:
    """
    Create a new workspace-scoped tag and emit a ``created`` audit row.

    Duplicate ``(workspace_id, name)`` pairs are rejected with
    :class:`ValidationError` rather than surfaced as a 500 from the
    underlying ``UNIQUE`` constraint. Re-creating a name that was
    previously soft-deleted in the same workspace is also rejected,
    because the uniqueness constraint in the schema is unconditional.
    """
    existing = session.execute(
        select(Tag).where(
            Tag.workspace_id == workspace_id,
            Tag.name == payload.name,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValidationError(
            "name",
            f"tag {payload.name!r} already exists in this workspace",
        )

    tag = Tag(
        workspace_id=workspace_id,
        name=payload.name,
        color=payload.color,
    )
    session.add(tag)
    session.flush()

    after = _dump(tag)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.TAG,
        entity_id=tag.id,
        action=AuditAction.CREATED,
        before=None,
        after=after,
    )
    publish_event(
        session,
        event_type="tag.created",
        actor=actor,
        entity_type=AuditEntityType.TAG.value,
        entity_id=tag.id,
        entity_version=None,
        payload=after,
    )
    return tag


def list_tags(
    session: Session,
    *,
    workspace_id: str,
    include_deleted: bool = False,
) -> list[Tag]:
    """
    Return every tag in ``workspace_id`` ordered by name.
    """
    stmt = (
        select(Tag).where(Tag.workspace_id == workspace_id).order_by(Tag.name, Tag.id)
    )
    if not include_deleted:
        stmt = live(stmt, Tag)
    return list(session.execute(stmt).scalars().all())


def list_tags_for_story(
    session: Session,
    *,
    story_id: str,
) -> list[Tag]:
    """
    Return every live tag associated with ``story_id`` ordered by name.

    Raises :class:`NotFoundError` if the story does not exist or has
    been soft-deleted. The story-side ``story_tags`` table has no
    lifecycle of its own: when a tag is soft-deleted the association
    is removed, so a soft-deleted tag can never appear in the result.
    """
    _get_live_story(session, story_id)
    stmt = (
        select(Tag)
        .join(story_tags, story_tags.c.tag_id == Tag.id)
        .where(story_tags.c.story_id == story_id)
        .order_by(Tag.name, Tag.id)
    )
    stmt = live(stmt, Tag)
    return list(session.execute(stmt).scalars().all())


def get_tag(
    session: Session,
    *,
    tag_id: str,
    include_deleted: bool = False,
) -> Tag:
    """
    Return a tag by id or raise :class:`NotFoundError`.
    """
    tag = session.get(Tag, tag_id)
    if tag is None:
        raise NotFoundError("tag", tag_id)
    if tag.deleted_at is not None and not include_deleted:
        raise NotFoundError("tag", tag_id)
    return tag


def update_tag(
    session: Session,
    *,
    actor: Actor,
    tag_id: str,
    payload: TagUpdate,
) -> Tag:
    """
    Apply a ``PATCH`` payload to a tag.

    Patches ``name`` and/or ``color``. Renaming enforces workspace
    uniqueness (raises :class:`ValidationError` on collision). Per spec
    §10 Q7, the rename history lives in the audit diff naturally; no
    extra bookkeeping is required here.
    """
    tag = _get_live_tag(session, tag_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return tag

    if "name" in updates and updates["name"] != tag.name:
        collision = session.execute(
            select(Tag).where(
                Tag.workspace_id == tag.workspace_id,
                Tag.name == updates["name"],
                Tag.id != tag.id,
            )
        ).scalar_one_or_none()
        if collision is not None:
            raise ValidationError(
                "name",
                f"tag {updates['name']!r} already exists in this workspace",
            )

    before = _dump(tag)
    for field, value in updates.items():
        setattr(tag, field, value)
    session.flush()

    after = _dump(tag)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.TAG,
        entity_id=tag.id,
        action=AuditAction.UPDATED,
        before=before,
        after=after,
    )
    publish_event(
        session,
        event_type="tag.updated",
        actor=actor,
        entity_type=AuditEntityType.TAG.value,
        entity_id=tag.id,
        entity_version=None,
        payload=after,
    )
    return tag


def soft_delete_tag(
    session: Session,
    *,
    actor: Actor,
    tag_id: str,
) -> Tag:
    """
    Mark a tag as deleted and detach it from every story.

    Per ``docs/spec.md`` section 4.2, tag soft-delete "detaches from
    stories": every ``story_tags`` row referencing this tag is removed
    in the same transaction, before ``deleted_at`` is stamped. The
    detach is treated as an implementation detail of the tag lifecycle
    and does **not** emit per-story audit rows; only a single
    ``soft_deleted`` row on the tag itself is emitted. Clients
    inspecting a story's audit trail after a tag delete will not see a
    ``tag_removed`` event, because from their perspective the story
    itself did not change: only the tag went away.
    """
    tag = _get_live_tag(session, tag_id)

    session.execute(delete(story_tags).where(story_tags.c.tag_id == tag.id))

    before = _dump(tag)
    tag.deleted_at = utc_now_iso()
    session.flush()

    after = _dump(tag)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.TAG,
        entity_id=tag.id,
        action=AuditAction.SOFT_DELETED,
        before=before,
        after=after,
    )
    # Per spec §5.4 the tag delete raises a single ``tag.deleted``
    # event; no per-association ``story.tag_removed`` events are
    # published for the detach cascade. Clients refetch affected
    # stories in response to this event if they care.
    publish_event(
        session,
        event_type="tag.deleted",
        actor=actor,
        entity_type=AuditEntityType.TAG.value,
        entity_id=tag.id,
        entity_version=None,
        payload=after,
    )
    return tag


def find_similar_tags(
    session: Session,
    *,
    workspace_id: str,
    name: str,
    include_deleted: bool = False,
) -> list[Tag]:
    """
    Return tags in ``workspace_id`` whose name normalises to the same
    canonical form as ``name``.

    Mirrors :func:`kanberoo_core.services.stories.find_similar_stories`
    in spirit. Tags already enforce ``UNIQUE(workspace_id, name)``,
    so an exact-name lookup would return at most one row; this helper
    catches the visually-similar case (``UI`` vs ``ui`` vs ``u-i``)
    where the unique constraint would not.
    """
    needle = normalize_for_comparison(name)
    if not needle:
        return []
    stmt = select(Tag).where(Tag.workspace_id == workspace_id)
    if not include_deleted:
        stmt = live(stmt, Tag)
    stmt = stmt.order_by(Tag.id)
    candidates = list(session.execute(stmt).scalars().all())
    return [tag for tag in candidates if normalize_for_comparison(tag.name) == needle]


def add_tags_to_story(
    session: Session,
    *,
    actor: Actor,
    story_id: str,
    tag_ids: list[str],
) -> Story:
    """
    Associate ``tag_ids`` with ``story_id``, idempotently.

    All supplied tags must be live and must belong to the story's
    workspace; cross-workspace tagging raises
    :class:`ValidationError`. Already-associated tags are silently
    skipped so repeated calls converge on the same set.

    Emits one ``tag_added`` audit row per tag newly associated, with
    ``entity_type="story"`` and ``after.tag_id`` set. No audit row is
    written for tags that were already associated.
    """
    story = _get_live_story(session, story_id)

    if not tag_ids:
        return story

    # Deduplicate preserving order.
    seen: set[str] = set()
    unique_ids: list[str] = []
    for tag_id in tag_ids:
        if tag_id not in seen:
            seen.add(tag_id)
            unique_ids.append(tag_id)

    tags = list(
        session.execute(
            select(Tag).where(Tag.id.in_(unique_ids), Tag.deleted_at.is_(None))
        )
        .scalars()
        .all()
    )
    tags_by_id = {t.id: t for t in tags}
    for tag_id in unique_ids:
        tag = tags_by_id.get(tag_id)
        if tag is None:
            raise ValidationError(
                "tag_ids",
                f"tag {tag_id!r} not found",
            )
        if tag.workspace_id != story.workspace_id:
            raise ValidationError(
                "tag_ids",
                f"tag {tag_id!r} belongs to a different workspace",
            )

    existing_links = set(
        session.execute(
            select(story_tags.c.tag_id).where(
                story_tags.c.story_id == story_id,
                story_tags.c.tag_id.in_(unique_ids),
            )
        )
        .scalars()
        .all()
    )

    now = utc_now_iso()
    for tag_id in unique_ids:
        if tag_id in existing_links:
            continue
        session.execute(
            story_tags.insert().values(
                story_id=story_id,
                tag_id=tag_id,
                created_at=now,
            )
        )
        emit_audit(
            session,
            actor=actor,
            entity_type=AuditEntityType.STORY,
            entity_id=story_id,
            action=AuditAction.TAG_ADDED,
            before=None,
            after={"tag_id": tag_id},
        )
        publish_event(
            session,
            event_type="story.tag_added",
            actor=actor,
            entity_type=AuditEntityType.STORY.value,
            entity_id=story_id,
            entity_version=story.version,
            payload={"tag_id": tag_id},
        )

    session.flush()
    return story


def remove_tag_from_story(
    session: Session,
    *,
    actor: Actor,
    story_id: str,
    tag_id: str,
) -> Story:
    """
    Remove a single tag association from ``story_id``.

    Idempotent: if the association does not exist the call is a no-op
    and does **not** emit an audit row. When the row is actually
    removed, exactly one ``tag_removed`` audit row is emitted against
    the story with ``before.tag_id`` populated.
    """
    story = _get_live_story(session, story_id)

    existing = session.execute(
        select(story_tags.c.tag_id).where(
            story_tags.c.story_id == story_id,
            story_tags.c.tag_id == tag_id,
        )
    ).scalar_one_or_none()
    if existing is None:
        return story

    session.execute(
        delete(story_tags).where(
            story_tags.c.story_id == story_id,
            story_tags.c.tag_id == tag_id,
        )
    )
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.STORY,
        entity_id=story_id,
        action=AuditAction.TAG_REMOVED,
        before={"tag_id": tag_id},
        after=None,
    )
    publish_event(
        session,
        event_type="story.tag_removed",
        actor=actor,
        entity_type=AuditEntityType.STORY.value,
        entity_id=story_id,
        entity_version=story.version,
        payload={"tag_id": tag_id},
    )
    session.flush()
    return story
