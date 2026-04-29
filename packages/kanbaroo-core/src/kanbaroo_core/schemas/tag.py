"""
Pydantic schemas for tags.
"""

from kanbaroo_core.schemas._base import ReadModel, WriteModel


class TagCreate(WriteModel):
    """
    Payload for ``POST /workspaces/{id}/tags``.
    """

    name: str
    color: str | None = None


class TagUpdate(WriteModel):
    """
    Payload for ``PATCH /tags/{id}``. Both fields are optional so a tag
    can be renamed or recolored independently.
    """

    name: str | None = None
    color: str | None = None


class TagRead(ReadModel):
    """
    Server response for any tag read.
    """

    id: str
    workspace_id: str
    name: str
    color: str | None
    created_at: str
    deleted_at: str | None
