"""
SQLAlchemy ORM models for every Kanberoo entity.

Importing this module registers all tables on :data:`kanberoo_core.db.Base.metadata`.
Alembic and tests rely on that side-effect; do not lazy-import individual
models from elsewhere.
"""

from kanberoo_core.models.api_token import ApiToken
from kanberoo_core.models.audit import AuditEvent
from kanberoo_core.models.base import (
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)
from kanberoo_core.models.comment import Comment
from kanberoo_core.models.epic import Epic
from kanberoo_core.models.linkage import Linkage
from kanberoo_core.models.story import Story
from kanberoo_core.models.story_tag import story_tags
from kanberoo_core.models.tag import Tag
from kanberoo_core.models.workspace import Workspace, WorkspaceRepo

__all__ = [
    "ApiToken",
    "AuditEvent",
    "Comment",
    "Epic",
    "Linkage",
    "SoftDeleteMixin",
    "Story",
    "Tag",
    "TimestampMixin",
    "VersionMixin",
    "Workspace",
    "WorkspaceRepo",
    "story_tags",
]
