"""
Pydantic v2 schemas for every Kanberoo entity.

Conventions:

* ``*Create`` schemas describe what a client supplies to create an entity.
* ``*Update`` schemas have all-optional fields and are used for ``PATCH``.
* ``*Read`` schemas describe what the API returns. They are constructable
  directly from ORM objects via ``model_validate(obj)``.

``audit_events`` and ``api_tokens`` only have ``Read`` schemas in this
milestone; their write paths live in later milestones (audit emission and
auth respectively).
"""

from kanberoo_core.schemas.api_token import ApiTokenRead
from kanberoo_core.schemas.audit import AuditEventRead
from kanberoo_core.schemas.comment import CommentCreate, CommentRead, CommentUpdate
from kanberoo_core.schemas.epic import EpicCreate, EpicRead, EpicUpdate
from kanberoo_core.schemas.linkage import LinkageCreate, LinkageRead
from kanberoo_core.schemas.story import StoryCreate, StoryRead, StoryUpdate
from kanberoo_core.schemas.tag import TagCreate, TagRead, TagUpdate
from kanberoo_core.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceRepoCreate,
    WorkspaceRepoRead,
    WorkspaceUpdate,
)

__all__ = [
    "ApiTokenRead",
    "AuditEventRead",
    "CommentCreate",
    "CommentRead",
    "CommentUpdate",
    "EpicCreate",
    "EpicRead",
    "EpicUpdate",
    "LinkageCreate",
    "LinkageRead",
    "StoryCreate",
    "StoryRead",
    "StoryUpdate",
    "TagCreate",
    "TagRead",
    "TagUpdate",
    "WorkspaceCreate",
    "WorkspaceRead",
    "WorkspaceRepoCreate",
    "WorkspaceRepoRead",
    "WorkspaceUpdate",
]
