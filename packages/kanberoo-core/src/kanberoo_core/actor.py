"""
Actor: the identity attributed to every mutation.

Every write in Kanberoo is attributed to an actor. See ``docs/spec.md``
section 3.2 for the conceptual model and ``CLAUDE.md`` "Actor Attribution"
for the pattern: auth middleware resolves a token into an ``Actor`` and
services accept the actor as a parameter that flows into the audit log.

The dataclass is intentionally tiny and frozen so it can flow through
service calls as a value, be used as a dict key, and be compared for
equality without surprises.
"""

from dataclasses import dataclass

from kanberoo_core.enums import ActorType


@dataclass(frozen=True, slots=True)
class Actor:
    """
    Immutable identity of the caller performing a mutation.

    ``type`` is one of the three spec-defined actor categories
    (``human``, ``claude``, ``system``). ``id`` is a free-form label
    stamped into audit rows; for humans this is typically the OS user
    name, for Claude it may be ``outer-claude`` or a similar tag.
    """

    type: ActorType
    id: str
