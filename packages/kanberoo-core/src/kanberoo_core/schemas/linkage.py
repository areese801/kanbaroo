"""
Pydantic schemas for linkages.
"""

from kanberoo_core.enums import LinkEndpointType, LinkType
from kanberoo_core.schemas._base import ReadModel, WriteModel


class LinkageCreate(WriteModel):
    """
    Payload for ``POST /linkages``.
    """

    source_type: LinkEndpointType
    source_id: str
    target_type: LinkEndpointType
    target_id: str
    link_type: LinkType


class LinkageRead(ReadModel):
    """
    Server response for any linkage read.
    """

    id: str
    source_type: LinkEndpointType
    source_id: str
    target_type: LinkEndpointType
    target_id: str
    link_type: LinkType
    created_at: str
    deleted_at: str | None
