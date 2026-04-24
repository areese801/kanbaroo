"""
Pydantic v2 schemas for every Kanbaroo entity.

Conventions:

* ``*Create`` schemas describe what a client supplies to create an entity.
* ``*Update`` schemas have all-optional fields and are used for ``PATCH``.
* ``*Read`` schemas describe what the API returns. They are constructable
  directly from ORM objects via ``model_validate(obj)``.

``audit_events`` and ``api_tokens`` only have ``Read`` schemas in this
milestone; their write paths live in later milestones (audit emission and
auth respectively).
"""

from kanbaroo_core.schemas.api_token import (
    ApiTokenCreate,
    ApiTokenCreatedRead,
    ApiTokenRead,
)
from kanbaroo_core.schemas.audit import AuditEventRead
from kanbaroo_core.schemas.comment import CommentCreate, CommentRead, CommentUpdate
from kanbaroo_core.schemas.epic import EpicCreate, EpicRead, EpicUpdate
from kanbaroo_core.schemas.linkage import LinkageCreate, LinkageRead
from kanbaroo_core.schemas.story import (
    StoryCreate,
    StoryRead,
    StoryTransitionRequest,
    StoryUpdate,
)
from kanbaroo_core.schemas.tag import TagCreate, TagRead, TagUpdate
from kanbaroo_core.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceRepoCreate,
    WorkspaceRepoRead,
    WorkspaceUpdate,
)

__all__ = [
    "ApiTokenCreate",
    "ApiTokenCreatedRead",
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
    "StoryTransitionRequest",
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
