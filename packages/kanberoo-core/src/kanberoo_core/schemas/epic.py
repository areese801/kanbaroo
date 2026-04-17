"""
Pydantic schemas for epics.
"""

from kanberoo_core.enums import EpicState
from kanberoo_core.schemas._base import ReadModel, WriteModel


class EpicCreate(WriteModel):
    """
    Payload for creating an epic. ``human_id`` is allocated server-side
    via the workspace's shared issue counter and is not supplied by the
    client.
    """

    title: str
    description: str | None = None


class EpicUpdate(WriteModel):
    """
    Payload for ``PATCH /epics/{id}``.
    """

    title: str | None = None
    description: str | None = None
    state: EpicState | None = None


class EpicRead(ReadModel):
    """
    Server response for any epic read.
    """

    id: str
    workspace_id: str
    human_id: str
    title: str
    description: str | None
    state: EpicState
    created_at: str
    updated_at: str
    deleted_at: str | None
    version: int
