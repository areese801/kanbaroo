"""
Kanberoo core: SQLAlchemy models, Pydantic schemas, and shared utilities.

This package owns the canonical data model (see ``docs/spec.md`` section 3)
and exposes it for use by the API, CLI, TUI, and MCP packages. Business
logic and the audit emission helper are intentionally not yet implemented;
they will arrive in later milestones.
"""

from kanberoo_core import models, schemas
from kanberoo_core.db import Base
from kanberoo_core.enums import (
    ActorType,
    AuditAction,
    AuditEntityType,
    EpicState,
    LinkEndpointType,
    LinkType,
    StoryPriority,
    StoryState,
)
from kanberoo_core.id_generator import generate_human_id
from kanberoo_core.queries import live
from kanberoo_core.time import utc_now_iso

__version__ = "0.1.0"

__all__ = [
    "ActorType",
    "AuditAction",
    "AuditEntityType",
    "Base",
    "EpicState",
    "LinkEndpointType",
    "LinkType",
    "StoryPriority",
    "StoryState",
    "__version__",
    "generate_human_id",
    "live",
    "models",
    "schemas",
    "utc_now_iso",
]
