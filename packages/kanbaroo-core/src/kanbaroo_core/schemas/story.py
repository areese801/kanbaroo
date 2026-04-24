"""
Pydantic schemas for stories.
"""

from kanbaroo_core.enums import ActorType, StoryPriority, StoryState
from kanbaroo_core.schemas._base import ReadModel, WriteModel


class StoryCreate(WriteModel):
    """
    Payload for ``POST /workspaces/{id}/stories``.

    ``human_id`` and ``state`` are server-controlled; the initial state
    is always ``backlog``.
    """

    title: str
    description: str | None = None
    priority: StoryPriority = StoryPriority.NONE
    epic_id: str | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    pr_url: str | None = None


class StoryUpdate(WriteModel):
    """
    Payload for ``PATCH /stories/{id}``.

    ``state`` is intentionally not patchable here: state changes must go
    through ``POST /stories/{id}/transition`` so the API can record the
    state actor.
    """

    title: str | None = None
    description: str | None = None
    priority: StoryPriority | None = None
    epic_id: str | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    pr_url: str | None = None


class StoryTransitionRequest(WriteModel):
    """
    Payload for ``POST /stories/{id}/transition``.

    ``to_state`` is the target state; ``reason`` is an optional
    free-text note surfaced in the audit row under ``transition_reason``.
    """

    to_state: StoryState
    reason: str | None = None


class StoryRead(ReadModel):
    """
    Server response for any story read.
    """

    id: str
    workspace_id: str
    epic_id: str | None
    human_id: str
    title: str
    description: str | None
    priority: StoryPriority
    state: StoryState
    state_actor_type: ActorType | None
    state_actor_id: str | None
    branch_name: str | None
    commit_sha: str | None
    pr_url: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None
    version: int
