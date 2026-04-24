"""
Kanbaroo core: SQLAlchemy models, Pydantic schemas, and shared utilities.

This package owns the canonical data model (see ``docs/spec.md`` section 3)
and exposes it for use by the API, CLI, TUI, and MCP packages. Business
logic and the audit emission helper are intentionally not yet implemented;
they will arrive in later milestones.
"""

from kanbaroo_core import models, schemas, services
from kanbaroo_core.actor import Actor
from kanbaroo_core.auth import (
    create_token,
    generate_token_plaintext,
    hash_token,
    revoke_token,
    validate_token,
)
from kanbaroo_core.db import Base
from kanbaroo_core.enums import (
    ActorType,
    AuditAction,
    AuditEntityType,
    EpicState,
    LinkEndpointType,
    LinkType,
    StoryPriority,
    StoryState,
)
from kanbaroo_core.id_generator import generate_human_id
from kanbaroo_core.queries import live
from kanbaroo_core.time import utc_now_iso

__version__ = "0.2.2"

__all__ = [
    "Actor",
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
    "create_token",
    "generate_human_id",
    "generate_token_plaintext",
    "hash_token",
    "live",
    "models",
    "revoke_token",
    "schemas",
    "services",
    "utc_now_iso",
    "validate_token",
]
