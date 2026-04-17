"""
Enumerations used by Kanberoo models, schemas, and (eventually) services.

These are str-valued enums so SQLAlchemy stores the human-readable value
verbatim (no integer mapping) and so external readers see the same tokens
that appear in the spec and in the API.
"""

from enum import StrEnum


def enum_values[E: StrEnum](enum_cls: type[E]) -> list[str]:
    """
    Return the ``.value`` of every member of ``enum_cls``.

    Suitable for the SQLAlchemy ``Enum(..., values_callable=...)``
    argument. Without this, SQLAlchemy defaults to storing the enum
    ``name`` (e.g. ``HUMAN``), but the spec, migration CHECK
    constraints, and all external readers use the lowercase ``.value``
    form (e.g. ``human``).
    """
    return [member.value for member in enum_cls]


class ActorType(StrEnum):
    """
    Type of actor performing a mutation.

    See ``docs/spec.md`` section 3.2.
    """

    HUMAN = "human"
    CLAUDE = "claude"
    SYSTEM = "system"


class StoryState(StrEnum):
    """
    Story lifecycle state.

    Transition rules live in ``docs/spec.md`` section 4.3 and are enforced
    by the (forthcoming) service layer; this enum only defines the legal
    domain of values.
    """

    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"


class EpicState(StrEnum):
    """
    Epic lifecycle state.
    """

    OPEN = "open"
    CLOSED = "closed"


class StoryPriority(StrEnum):
    """
    Story priority level. Default is ``none``.
    """

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LinkType(StrEnum):
    """
    Allowed linkage relationship types.

    The ``blocks`` / ``is_blocked_by`` pair is mirrored by the service layer
    when one is created (see milestone 6 / spec section 3.1).
    """

    RELATES_TO = "relates_to"
    BLOCKS = "blocks"
    IS_BLOCKED_BY = "is_blocked_by"
    DUPLICATES = "duplicates"
    IS_DUPLICATED_BY = "is_duplicated_by"


class LinkEndpointType(StrEnum):
    """
    Allowed entity types as the source or target of a linkage.
    """

    STORY = "story"
    EPIC = "epic"


class AuditEntityType(StrEnum):
    """
    Entity types that can appear in the audit log.
    """

    WORKSPACE = "workspace"
    EPIC = "epic"
    STORY = "story"
    COMMENT = "comment"
    LINKAGE = "linkage"
    TAG = "tag"


class AuditAction(StrEnum):
    """
    Canonical audit actions.

    The DB column is plain text (no CHECK constraint) because the spec
    leaves room for future actions; this enum captures the ones in use
    today.
    """

    CREATED = "created"
    UPDATED = "updated"
    SOFT_DELETED = "soft_deleted"
    STATE_CHANGED = "state_changed"
    COMMENTED = "commented"
    LINKED = "linked"
    UNLINKED = "unlinked"
    TAG_ADDED = "tag_added"
    TAG_REMOVED = "tag_removed"
