"""
Pydantic schemas for API tokens.

Only a Read schema is persisted; token creation is fire-and-forget (the
caller is shown the plaintext exactly once and never again) so the
create schema is purely a request model. Token revocation takes no
payload.
"""

from kanberoo_core.enums import ActorType
from kanberoo_core.schemas._base import ReadModel, WriteModel


class ApiTokenCreate(WriteModel):
    """
    Payload for ``POST /tokens``.

    ``actor_type`` and ``actor_id`` are deliberately caller-supplied:
    the API is single-user in v1 so the caller is trusted to tag its
    own tokens (e.g. ``claude`` for an MCP-facing token vs. ``human``
    for a personal token).
    """

    actor_type: ActorType
    actor_id: str
    name: str


class ApiTokenRead(ReadModel):
    """
    Server response for any token read. ``token_hash`` is exposed because
    callers (admin tools) may need to identify a token without seeing its
    plaintext.
    """

    id: str
    token_hash: str
    actor_type: ActorType
    actor_id: str
    name: str
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


class ApiTokenCreatedRead(ApiTokenRead):
    """
    One-shot response for ``POST /tokens``.

    Extends :class:`ApiTokenRead` with the ``plaintext`` field. This
    plaintext is only ever present in the create response; subsequent
    reads return :class:`ApiTokenRead` without it.
    """

    plaintext: str
