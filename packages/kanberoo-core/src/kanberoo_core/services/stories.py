"""
Story CRUD and state-machine service.

Stories are the unit of work in Kanberoo. Their lifecycle is the
state machine defined in ``docs/spec.md`` section 4.3 and enforced here
by :data:`_ALLOWED_TRANSITIONS`. State transitions are routed through
:func:`transition_story` rather than :func:`update_story` so every move
stamps ``state_actor_type``/``state_actor_id`` and writes an audit row
with ``action="state_changed"``.

Per ``docs/spec.md`` section 10 Q3, reassigning a story's ``epic_id``
to an epic in a different workspace is rejected as a
:class:`ValidationError`. Users who want that behaviour should create a
new story in the target workspace and link it rather than silently
move the original.

As with epics, soft deletes do not cascade and every mutation emits
exactly one audit row within the caller's transaction.
"""

import base64
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kanberoo_core.actor import Actor
from kanberoo_core.enums import AuditAction, AuditEntityType, StoryPriority, StoryState
from kanberoo_core.id_generator import generate_human_id
from kanberoo_core.models.epic import Epic
from kanberoo_core.models.story import Story
from kanberoo_core.queries import live
from kanberoo_core.schemas.story import StoryCreate, StoryRead, StoryUpdate
from kanberoo_core.services.audit import emit_audit
from kanberoo_core.services.exceptions import (
    NotFoundError,
    ValidationError,
    VersionConflictError,
)
from kanberoo_core.time import utc_now_iso

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200


_ALLOWED_TRANSITIONS: dict[StoryState, frozenset[StoryState]] = {
    StoryState.BACKLOG: frozenset({StoryState.TODO}),
    StoryState.TODO: frozenset({StoryState.IN_PROGRESS, StoryState.BACKLOG}),
    StoryState.IN_PROGRESS: frozenset({StoryState.IN_REVIEW, StoryState.BACKLOG}),
    StoryState.IN_REVIEW: frozenset(
        {StoryState.DONE, StoryState.IN_PROGRESS, StoryState.BACKLOG}
    ),
    StoryState.DONE: frozenset({StoryState.IN_REVIEW, StoryState.BACKLOG}),
}


class InvalidStateTransitionError(ValidationError):
    """
    Raised when :func:`transition_story` is asked to move a story into
    a state that is not reachable from its current state.

    Inherits :class:`ValidationError` so the API layer renders it as a
    ``400 validation_error``; the ``details`` carry both ``from_state``
    and ``to_state`` for the client to act on.
    """

    def __init__(self, from_state: StoryState, to_state: StoryState) -> None:
        super().__init__(
            field="to_state",
            message=(
                f"cannot transition story from {from_state.value} to {to_state.value}"
            ),
        )
        self.details["from_state"] = from_state.value
        self.details["to_state"] = to_state.value
        self.from_state = from_state
        self.to_state = to_state


def _dump(story: Story) -> dict[str, Any]:
    """
    Serialise a :class:`Story` row into a JSON-friendly dict for the
    audit log.
    """
    return StoryRead.model_validate(story).model_dump(mode="json")


def _encode_cursor(story_id: str) -> str:
    """
    Encode a story id as an opaque URL-safe cursor.
    """
    return base64.urlsafe_b64encode(story_id.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> str:
    """
    Decode a cursor back into the story id it wraps.

    Raises :class:`ValidationError` if the cursor is not valid base64
    URL-safe data; this translates to a 400 at the API layer.
    """
    try:
        return base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("cursor", "malformed cursor value") from exc


def _verify_epic_in_workspace(
    session: Session,
    *,
    epic_id: str,
    workspace_id: str,
) -> None:
    """
    Ensure ``epic_id`` references a live epic belonging to
    ``workspace_id``.

    Used by :func:`create_story` and :func:`update_story` to enforce
    the spec's "no auto cross-workspace move" rule. Raises
    :class:`ValidationError` on any of: unknown epic, soft-deleted
    epic, or epic owned by a different workspace.
    """
    epic = session.get(Epic, epic_id)
    if epic is None or epic.deleted_at is not None:
        raise ValidationError(
            "epic_id",
            f"epic {epic_id!r} not found",
        )
    if epic.workspace_id != workspace_id:
        raise ValidationError(
            "epic_id",
            (
                f"epic {epic_id!r} belongs to a different workspace; "
                "create a new story in the target workspace instead"
            ),
        )


def create_story(
    session: Session,
    *,
    actor: Actor,
    workspace_id: str,
    payload: StoryCreate,
) -> Story:
    """
    Create a new story and emit an audit event.

    If ``payload.epic_id`` is set, the referenced epic must exist,
    belong to ``workspace_id``, and not be soft-deleted; otherwise
    :class:`ValidationError` is raised. Allocates the next
    ``{KEY}-{N}`` human identifier from the workspace's shared counter.
    """
    if payload.epic_id is not None:
        _verify_epic_in_workspace(
            session,
            epic_id=payload.epic_id,
            workspace_id=workspace_id,
        )

    try:
        human_id = generate_human_id(session, workspace_id)
    except ValueError as exc:
        raise NotFoundError("workspace", workspace_id) from exc

    story = Story(
        workspace_id=workspace_id,
        epic_id=payload.epic_id,
        human_id=human_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        branch_name=payload.branch_name,
        commit_sha=payload.commit_sha,
        pr_url=payload.pr_url,
    )
    session.add(story)
    session.flush()

    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.STORY,
        entity_id=story.id,
        action=AuditAction.CREATED,
        before=None,
        after=_dump(story),
    )
    return story


def list_stories(
    session: Session,
    *,
    workspace_id: str,
    state: StoryState | None = None,
    priority: StoryPriority | None = None,
    epic_id: str | None = None,
    tag: str | None = None,
    include_deleted: bool = False,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> tuple[list[Story], str | None]:
    """
    Return a page of stories in a workspace plus a cursor for the next
    page.

    Supports the filters documented in ``docs/spec.md`` section 4.1:
    ``state``, ``priority``, ``epic_id``. The ``tag`` parameter is
    accepted for forward compatibility but not yet wired; tag filtering
    lands with the tags REST surface in cage E. Callers passing
    ``tag`` today receive the unfiltered result for that dimension.
    """
    # `tag` is accepted but deferred to cage E; see module docstring.
    del tag

    if limit < 1:
        limit = 1
    if limit > MAX_PAGE_LIMIT:
        limit = MAX_PAGE_LIMIT

    stmt = select(Story).where(Story.workspace_id == workspace_id).order_by(Story.id)
    if state is not None:
        stmt = stmt.where(Story.state == state)
    if priority is not None:
        stmt = stmt.where(Story.priority == priority)
    if epic_id is not None:
        stmt = stmt.where(Story.epic_id == epic_id)
    if not include_deleted:
        stmt = live(stmt, Story)
    if cursor is not None:
        stmt = stmt.where(Story.id > _decode_cursor(cursor))
    stmt = stmt.limit(limit + 1)

    rows = list(session.execute(stmt).scalars().all())
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1].id)
    return rows, next_cursor


def get_story(
    session: Session,
    *,
    story_id: str,
    include_deleted: bool = False,
) -> Story:
    """
    Return a story by id or raise :class:`NotFoundError`.

    By default soft-deleted rows are treated as missing; pass
    ``include_deleted=True`` to read an archived story.
    """
    story = session.get(Story, story_id)
    if story is None:
        raise NotFoundError("story", story_id)
    if story.deleted_at is not None and not include_deleted:
        raise NotFoundError("story", story_id)
    return story


def get_story_by_human_id(
    session: Session,
    *,
    human_id: str,
    include_deleted: bool = False,
) -> Story:
    """
    Return a story by its ``{KEY}-{N}`` human identifier or raise
    :class:`NotFoundError`.

    Used by the ``GET /stories/by-key/{human_id}`` endpoint. Soft-
    deleted rows are hidden unless ``include_deleted`` is ``True``.
    """
    stmt = select(Story).where(Story.human_id == human_id)
    story = session.execute(stmt).scalar_one_or_none()
    if story is None:
        raise NotFoundError("story", human_id)
    if story.deleted_at is not None and not include_deleted:
        raise NotFoundError("story", human_id)
    return story


def update_story(
    session: Session,
    *,
    actor: Actor,
    story_id: str,
    expected_version: int,
    payload: StoryUpdate,
) -> Story:
    """
    Apply a ``PATCH`` payload to a story.

    Patchable fields: ``title``, ``description``, ``priority``,
    ``epic_id``, ``branch_name``, ``commit_sha``, ``pr_url``. State
    transitions are intentionally not patchable here; use
    :func:`transition_story`.

    If ``epic_id`` is present in the payload the target epic must
    belong to the same workspace as the story, per spec section 10 Q3;
    cross-workspace reassignment is rejected with
    :class:`ValidationError`. A payload that explicitly sets
    ``epic_id`` to ``None`` detaches the story from its epic.
    """
    story = get_story(session, story_id=story_id)
    if story.version != expected_version:
        raise VersionConflictError(
            "story",
            story_id,
            expected_version,
            story.version,
        )

    updates = payload.model_dump(exclude_unset=True)
    if "epic_id" in updates and updates["epic_id"] is not None:
        _verify_epic_in_workspace(
            session,
            epic_id=updates["epic_id"],
            workspace_id=story.workspace_id,
        )

    before = _dump(story)
    for field, value in updates.items():
        setattr(story, field, value)
    session.flush()

    after = _dump(story)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.STORY,
        entity_id=story.id,
        action=AuditAction.UPDATED,
        before=before,
        after=after,
    )
    return story


def soft_delete_story(
    session: Session,
    *,
    actor: Actor,
    story_id: str,
    expected_version: int,
) -> Story:
    """
    Mark a story as deleted by stamping ``deleted_at``.
    """
    story = get_story(session, story_id=story_id)
    if story.version != expected_version:
        raise VersionConflictError(
            "story",
            story_id,
            expected_version,
            story.version,
        )

    before = _dump(story)
    story.deleted_at = utc_now_iso()
    session.flush()

    after = _dump(story)
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.STORY,
        entity_id=story.id,
        action=AuditAction.SOFT_DELETED,
        before=before,
        after=after,
    )
    return story


def transition_story(
    session: Session,
    *,
    actor: Actor,
    story_id: str,
    expected_version: int,
    to_state: StoryState,
    reason: str | None = None,
) -> Story:
    """
    Move a story to a new state, enforcing the state machine.

    Validates the transition against :data:`_ALLOWED_TRANSITIONS`;
    invalid moves (including ``to_state == current``) raise
    :class:`InvalidStateTransitionError`. On success the story's
    ``state`` is updated and ``state_actor_type`` / ``state_actor_id``
    are stamped from ``actor``. A single audit row is emitted with
    ``action="state_changed"`` whose ``after`` dict additionally
    carries the caller-supplied ``transition_reason`` when present.
    """
    story = get_story(session, story_id=story_id)
    if story.version != expected_version:
        raise VersionConflictError(
            "story",
            story_id,
            expected_version,
            story.version,
        )

    # Pydantic's ``use_enum_values=True`` means the transport-layer
    # payload may hand us the raw string rather than the StoryState
    # member; normalise so downstream comparisons and ``emit_audit``
    # always see the enum.
    target_state = StoryState(to_state)
    current_state = StoryState(story.state)
    if target_state not in _ALLOWED_TRANSITIONS.get(current_state, frozenset()):
        raise InvalidStateTransitionError(current_state, target_state)

    before = _dump(story)
    story.state = target_state
    story.state_actor_type = actor.type
    story.state_actor_id = actor.id
    session.flush()

    after = _dump(story)
    if reason is not None:
        after["transition_reason"] = reason
    emit_audit(
        session,
        actor=actor,
        entity_type=AuditEntityType.STORY,
        entity_id=story.id,
        action=AuditAction.STATE_CHANGED,
        before=before,
        after=after,
    )
    return story
