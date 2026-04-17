"""
Pydantic schema for API tokens.

Only a Read schema is provided in this milestone. Token creation,
hashing, and the one-time plaintext response live in milestone 3.
"""

from kanberoo_core.enums import ActorType
from kanberoo_core.schemas._base import ReadModel


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
