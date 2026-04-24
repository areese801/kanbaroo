"""
Service-layer tests that assert WebSocket events fire in parallel with
audit rows.

Each test subscribes to :data:`kanbaroo_core.events.default_bus`, runs a
service mutation followed by a commit, and inspects the events drained
from the bus. The per-test setup uses ``pytest-asyncio`` (auto mode) so
subscriptions live on the same event loop as the commit call.

The load-bearing invariant here is **events publish if and only if the
transaction commits**. One test explicitly rolls back the session and
asserts no events arrive.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.orm import Session

from kanbaroo_core import Actor, ActorType
from kanbaroo_core.enums import LinkEndpointType, LinkType, StoryState
from kanbaroo_core.events import Event, default_bus
from kanbaroo_core.schemas.comment import CommentCreate, CommentUpdate
from kanbaroo_core.schemas.epic import EpicCreate, EpicUpdate
from kanbaroo_core.schemas.linkage import LinkageCreate
from kanbaroo_core.schemas.story import StoryCreate, StoryUpdate
from kanbaroo_core.schemas.tag import TagCreate, TagUpdate
from kanbaroo_core.schemas.workspace import WorkspaceCreate, WorkspaceUpdate
from kanbaroo_core.services import (
    comments as comment_service,
)
from kanbaroo_core.services import (
    epics as epic_service,
)
from kanbaroo_core.services import (
    linkages as linkage_service,
)
from kanbaroo_core.services import (
    stories as story_service,
)
from kanbaroo_core.services import (
    tags as tag_service,
)
from kanbaroo_core.services import (
    workspaces as ws_service,
)
from kanbaroo_core.services.exceptions import ValidationError

HUMAN = Actor(type=ActorType.HUMAN, id="adam")


class EventCollector:
    """
    Test helper that drains events off the shared default bus into a
    list, with an async ``wait_for`` that polls until expected event
    types arrive (or a short timeout elapses).
    """

    def __init__(self) -> None:
        self.events: list[Event] = []

    def types(self) -> list[str]:
        """
        Return the ordered list of ``event_type`` strings seen so far.
        """
        return [e.event_type for e in self.events]


@asynccontextmanager
async def _collect_events() -> AsyncIterator[EventCollector]:
    """
    Open a subscription against the default bus and yield a collector.

    The collector runs a background task that appends each incoming
    event to its list. On exit the task is cancelled and the
    subscription torn down.
    """
    collector = EventCollector()

    async def _drain() -> None:
        async for event in default_bus.subscribe():
            collector.events.append(event)

    task = asyncio.create_task(_drain())
    # Yield once so the subscription registers before the caller
    # triggers any mutation.
    while default_bus.subscriber_count < 1:
        await asyncio.sleep(0)
    try:
        yield collector
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _settle() -> None:
    """
    Yield control enough times for queued events to drain onto a
    collector's list.

    Events are scheduled via ``loop.call_soon_threadsafe`` then the
    subscriber wakes from ``queue.get()`` and appends to its list;
    each step requires one event loop iteration.
    """
    for _ in range(5):
        await asyncio.sleep(0)


async def test_create_workspace_publishes_event(session: Session) -> None:
    """
    Creating a workspace publishes a single ``workspace.created``
    event after the transaction commits.
    """
    async with _collect_events() as collector:
        workspace = ws_service.create_workspace(
            session,
            actor=HUMAN,
            payload=WorkspaceCreate(key="KAN", name="Kanbaroo"),
        )
        session.commit()
        await _settle()

    assert collector.types() == ["workspace.created"]
    event = collector.events[0]
    assert event.entity_type == "workspace"
    assert event.entity_id == workspace.id
    assert event.entity_version == workspace.version
    assert event.actor_type == "human"
    assert event.actor_id == "adam"
    assert event.payload["key"] == "KAN"


async def test_update_and_delete_workspace_publish_events(session: Session) -> None:
    """
    Update and soft-delete publish ``workspace.updated`` and
    ``workspace.deleted`` respectively.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanbaroo"),
    )
    session.commit()

    async with _collect_events() as collector:
        ws_service.update_workspace(
            session,
            actor=HUMAN,
            workspace_id=workspace.id,
            expected_version=workspace.version,
            payload=WorkspaceUpdate(name="Renamed"),
        )
        session.commit()
        ws_service.soft_delete_workspace(
            session,
            actor=HUMAN,
            workspace_id=workspace.id,
            expected_version=workspace.version,
        )
        session.commit()
        await _settle()

    assert collector.types() == ["workspace.updated", "workspace.deleted"]


async def test_rollback_suppresses_events(session: Session) -> None:
    """
    If the surrounding transaction is rolled back instead of
    committed, no events reach subscribers.
    """
    async with _collect_events() as collector:
        ws_service.create_workspace(
            session,
            actor=HUMAN,
            payload=WorkspaceCreate(key="KAN", name="Kanbaroo"),
        )
        session.rollback()
        # Perform a second mutation after the rollback and commit it;
        # only this one should be published.
        ws_service.create_workspace(
            session,
            actor=HUMAN,
            payload=WorkspaceCreate(key="ENG", name="Engineering"),
        )
        session.commit()
        await _settle()

    assert collector.types() == ["workspace.created"]
    assert collector.events[0].payload["key"] == "ENG"


async def test_epic_lifecycle_publishes_events(session: Session) -> None:
    """
    Epic create, update, close/reopen, and soft-delete each publish
    their expected event types.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanbaroo"),
    )
    session.commit()

    async with _collect_events() as collector:
        epic = epic_service.create_epic(
            session,
            actor=HUMAN,
            workspace_id=workspace.id,
            payload=EpicCreate(title="Milestone 8"),
        )
        session.commit()
        epic_service.update_epic(
            session,
            actor=HUMAN,
            epic_id=epic.id,
            expected_version=epic.version,
            payload=EpicUpdate(title="Milestone 8 (events)"),
        )
        session.commit()
        epic_service.close_epic(
            session,
            actor=HUMAN,
            epic_id=epic.id,
            expected_version=epic.version,
        )
        session.commit()
        epic_service.soft_delete_epic(
            session,
            actor=HUMAN,
            epic_id=epic.id,
            expected_version=epic.version,
        )
        session.commit()
        await _settle()

    # close() reuses the ``epic.updated`` event_type because state is
    # one field among others; soft_delete publishes ``epic.deleted``.
    assert collector.types() == [
        "epic.created",
        "epic.updated",
        "epic.updated",
        "epic.deleted",
    ]


async def test_story_lifecycle_and_transition(session: Session) -> None:
    """
    Story CRUD plus a valid ``backlog → todo`` transition publishes:
    create, update, transitioned. The transition payload carries
    ``from_state``, ``to_state``, and the optional ``reason``.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanbaroo"),
    )
    session.commit()

    async with _collect_events() as collector:
        story = story_service.create_story(
            session,
            actor=HUMAN,
            workspace_id=workspace.id,
            payload=StoryCreate(title="Add WS event stream"),
        )
        session.commit()
        story_service.update_story(
            session,
            actor=HUMAN,
            story_id=story.id,
            expected_version=story.version,
            payload=StoryUpdate(title="Ship WS event stream"),
        )
        session.commit()
        story_service.transition_story(
            session,
            actor=HUMAN,
            story_id=story.id,
            expected_version=story.version,
            to_state=StoryState.TODO,
            reason="ready to pick up",
        )
        session.commit()
        story_service.soft_delete_story(
            session,
            actor=HUMAN,
            story_id=story.id,
            expected_version=story.version,
        )
        session.commit()
        await _settle()

    assert collector.types() == [
        "story.created",
        "story.updated",
        "story.transitioned",
        "story.deleted",
    ]
    transition = collector.events[2]
    assert transition.payload == {
        "workspace_id": workspace.id,
        "story_id": story.id,
        "from_state": "backlog",
        "to_state": "todo",
        "reason": "ready to pick up",
    }


async def test_story_transition_without_reason_omits_it(session: Session) -> None:
    """
    ``reason`` is optional; when the caller omits it, the event
    payload does not carry a stale ``reason`` field.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanbaroo"),
    )
    session.commit()
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace.id,
        payload=StoryCreate(title="Event stream"),
    )
    session.commit()

    async with _collect_events() as collector:
        story_service.transition_story(
            session,
            actor=HUMAN,
            story_id=story.id,
            expected_version=story.version,
            to_state=StoryState.TODO,
        )
        session.commit()
        await _settle()

    assert collector.types() == ["story.transitioned"]
    assert collector.events[0].payload == {
        "workspace_id": workspace.id,
        "story_id": story.id,
        "from_state": "backlog",
        "to_state": "todo",
    }


async def test_comment_lifecycle_publishes_events(session: Session) -> None:
    """
    Comment create publishes ``story.commented``; subsequent update
    and soft-delete publish ``comment.updated`` / ``comment.deleted``.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanbaroo"),
    )
    session.commit()
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace.id,
        payload=StoryCreate(title="First"),
    )
    session.commit()

    async with _collect_events() as collector:
        comment = comment_service.create_comment(
            session,
            actor=HUMAN,
            story_id=story.id,
            payload=CommentCreate(body="LGTM"),
        )
        session.commit()
        comment_service.update_comment(
            session,
            actor=HUMAN,
            comment_id=comment.id,
            expected_version=comment.version,
            payload=CommentUpdate(body="LGTM +1"),
        )
        session.commit()
        comment_service.soft_delete_comment(
            session,
            actor=HUMAN,
            comment_id=comment.id,
            expected_version=comment.version,
        )
        session.commit()
        await _settle()

    assert collector.types() == [
        "story.commented",
        "comment.updated",
        "comment.deleted",
    ]
    created = collector.events[0]
    assert created.entity_type == "story"
    assert created.entity_id == story.id
    assert created.entity_version is None
    assert created.payload["body"] == "LGTM"


async def test_tag_lifecycle_and_story_tag_events(session: Session) -> None:
    """
    Tag CRUD publishes ``tag.created`` / ``tag.updated`` / ``tag.deleted``
    with ``entity_version=None`` (tags have no version column). Story
    tag association publishes ``story.tag_added`` with ``{tag_id}`` in
    the payload; removal publishes ``story.tag_removed``.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanbaroo"),
    )
    session.commit()
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace.id,
        payload=StoryCreate(title="Bug"),
    )
    session.commit()

    async with _collect_events() as collector:
        tag = tag_service.create_tag(
            session,
            actor=HUMAN,
            workspace_id=workspace.id,
            payload=TagCreate(name="bug"),
        )
        session.commit()
        tag_service.update_tag(
            session,
            actor=HUMAN,
            tag_id=tag.id,
            payload=TagUpdate(color="#cc3333"),
        )
        session.commit()
        tag_service.add_tags_to_story(
            session,
            actor=HUMAN,
            story_id=story.id,
            tag_ids=[tag.id],
        )
        session.commit()
        tag_service.remove_tag_from_story(
            session,
            actor=HUMAN,
            story_id=story.id,
            tag_id=tag.id,
        )
        session.commit()
        tag_service.soft_delete_tag(session, actor=HUMAN, tag_id=tag.id)
        session.commit()
        await _settle()

    assert collector.types() == [
        "tag.created",
        "tag.updated",
        "story.tag_added",
        "story.tag_removed",
        "tag.deleted",
    ]
    tag_created = collector.events[0]
    assert tag_created.entity_version is None
    tag_added = collector.events[2]
    assert tag_added.entity_type == "story"
    assert tag_added.payload == {"tag_id": tag.id}
    tag_removed = collector.events[3]
    assert tag_removed.payload == {"tag_id": tag.id}


async def test_linkage_create_and_delete_publish_forward_only(
    session: Session,
) -> None:
    """
    Creating a mirrored ``blocks`` linkage publishes a single
    ``story.linked`` event for the forward row; the mirror stays
    silent. Deleting it publishes a single ``story.unlinked`` event.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanbaroo"),
    )
    session.commit()
    blocker = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace.id,
        payload=StoryCreate(title="Blocker"),
    )
    blocked = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace.id,
        payload=StoryCreate(title="Blocked"),
    )
    session.commit()

    async with _collect_events() as collector:
        linkage = linkage_service.create_linkage(
            session,
            actor=HUMAN,
            payload=LinkageCreate(
                source_type=LinkEndpointType.STORY,
                source_id=blocker.id,
                target_type=LinkEndpointType.STORY,
                target_id=blocked.id,
                link_type=LinkType.BLOCKS,
            ),
        )
        session.commit()
        linkage_service.delete_linkage(
            session,
            actor=HUMAN,
            linkage_id=linkage.id,
        )
        session.commit()
        await _settle()

    assert collector.types() == ["story.linked", "story.unlinked"]
    linked = collector.events[0]
    assert linked.entity_type == "linkage"
    assert linked.entity_id == linkage.id
    assert linked.payload["link_type"] == "blocks"


async def test_epic_linkage_uses_epic_prefix(session: Session) -> None:
    """
    When the linkage's source endpoint is an epic, the event_type is
    ``epic.linked`` (and ``epic.unlinked`` on delete). Decision
    documented in the linkage service docstring.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanbaroo"),
    )
    session.commit()
    epic = epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=workspace.id,
        payload=EpicCreate(title="Milestone"),
    )
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace.id,
        payload=StoryCreate(title="Story"),
    )
    session.commit()

    async with _collect_events() as collector:
        linkage = linkage_service.create_linkage(
            session,
            actor=HUMAN,
            payload=LinkageCreate(
                source_type=LinkEndpointType.EPIC,
                source_id=epic.id,
                target_type=LinkEndpointType.STORY,
                target_id=story.id,
                link_type=LinkType.RELATES_TO,
            ),
        )
        session.commit()
        linkage_service.delete_linkage(
            session,
            actor=HUMAN,
            linkage_id=linkage.id,
        )
        session.commit()
        await _settle()

    assert collector.types() == ["epic.linked", "epic.unlinked"]


async def test_duplicate_linkage_create_delete_still_single_event(
    session: Session,
) -> None:
    """
    Duplication pairs also fire exactly one ``linked`` event and one
    ``unlinked`` event; the mirror is silent.
    """
    workspace = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanbaroo"),
    )
    session.commit()
    a = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace.id,
        payload=StoryCreate(title="A"),
    )
    b = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=workspace.id,
        payload=StoryCreate(title="B"),
    )
    session.commit()

    async with _collect_events() as collector:
        linkage = linkage_service.create_linkage(
            session,
            actor=HUMAN,
            payload=LinkageCreate(
                source_type=LinkEndpointType.STORY,
                source_id=a.id,
                target_type=LinkEndpointType.STORY,
                target_id=b.id,
                link_type=LinkType.DUPLICATES,
            ),
        )
        session.commit()
        linkage_service.delete_linkage(
            session,
            actor=HUMAN,
            linkage_id=linkage.id,
        )
        session.commit()
        await _settle()

    assert collector.types() == ["story.linked", "story.unlinked"]


async def test_validation_error_emits_no_events(session: Session) -> None:
    """
    A service call that raises before reaching ``emit_audit`` produces
    no events: the session rollback invariant means the transaction is
    rolled back, and ``after_rollback`` clears any buffered events.
    """
    ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanbaroo"),
    )
    session.commit()

    async with _collect_events() as collector:
        with pytest.raises(ValidationError):
            ws_service.create_workspace(
                session,
                actor=HUMAN,
                payload=WorkspaceCreate(key="KAN", name="duplicate"),
            )
        session.rollback()
        await _settle()

    assert collector.types() == []
