"""
Pydantic schemas for comments.
"""

from kanbaroo_core.enums import ActorType
from kanbaroo_core.schemas._base import ReadModel, WriteModel


class CommentCreate(WriteModel):
    """
    Payload for ``POST /stories/{id}/comments``. The actor is derived
    from the auth token; the client never supplies it.
    """

    body: str
    parent_id: str | None = None


class CommentUpdate(WriteModel):
    """
    Payload for ``PATCH /comments/{id}``.
    """

    body: str | None = None


class CommentRead(ReadModel):
    """
    Server response for any comment read.
    """

    id: str
    story_id: str
    parent_id: str | None
    body: str
    actor_type: ActorType
    actor_id: str
    created_at: str
    updated_at: str
    deleted_at: str | None
    version: int
