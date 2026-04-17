"""
Token creation, hashing, and validation helpers.

These primitives are the bottom half of the auth layer. The top half
(the FastAPI ``Authorization: Bearer`` dependency that turns a request
into an :class:`~kanberoo_core.actor.Actor`) lands in milestone 4 with
the rest of the API scaffold.

Conventions (see ``docs/spec.md`` sections 3.3 and 4.1):

- Plaintext tokens are ``kbr_``-prefixed, URL-safe random strings. The
  prefix makes them grep-able in logs and distinguishable from other
  opaque IDs.
- The database only ever stores the SHA-256 hex digest in
  ``api_tokens.token_hash``. The plaintext is shown to the caller
  exactly once, at creation time, and is never recoverable afterwards.
- Validation updates ``last_used_at`` on success so that idle tokens
  are identifiable.
- Revocation is idempotent: revoking an already-revoked token is a
  no-op.
"""

import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from kanberoo_core.actor import Actor
from kanberoo_core.enums import ActorType
from kanberoo_core.models.api_token import ApiToken
from kanberoo_core.time import utc_now_iso

TOKEN_PREFIX = "kbr_"


def hash_token(plaintext: str) -> str:
    """
    Return the SHA-256 hex digest of the given plaintext token.

    The digest is what gets stored in ``api_tokens.token_hash``; lookup
    by plaintext works by hashing the candidate and comparing against
    the stored digest.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate_token_plaintext() -> str:
    """
    Generate a fresh, cryptographically secure bearer token.

    The token is 32 bytes of randomness from :mod:`secrets` encoded with
    URL-safe base64 and prefixed with ``kbr_`` so it is recognisable if
    it leaks into a log line.
    """
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def create_token(
    session: Session,
    *,
    actor_type: ActorType,
    actor_id: str,
    name: str,
) -> tuple[ApiToken, str]:
    """
    Create a new API token and return the row plus its plaintext.

    Generates a fresh plaintext, hashes it, creates an ``api_tokens``
    row with ``created_at=utc_now_iso()``, and flushes the session so
    the row's defaults (UUID v7 primary key) are populated. The caller
    is responsible for committing the surrounding transaction and for
    displaying the returned plaintext to the user exactly once; it is
    unrecoverable after that.
    """
    plaintext = generate_token_plaintext()
    token = ApiToken(
        token_hash=hash_token(plaintext),
        actor_type=actor_type,
        actor_id=actor_id,
        name=name,
        created_at=utc_now_iso(),
    )
    session.add(token)
    session.flush()
    return token, plaintext


def validate_token(session: Session, plaintext: str) -> Actor | None:
    """
    Resolve a plaintext token to its :class:`Actor`, or ``None``.

    Hashes the candidate, looks up the matching row, and returns the
    attributed actor. Returns ``None`` if the hash is unknown or the
    token has been revoked. On success, stamps ``last_used_at`` with
    the current UTC timestamp; callers commit the surrounding
    transaction.
    """
    digest = hash_token(plaintext)
    row = session.execute(
        select(ApiToken).where(ApiToken.token_hash == digest)
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    row.last_used_at = utc_now_iso()
    return Actor(type=row.actor_type, id=row.actor_id)


def revoke_token(session: Session, token_id: str) -> None:
    """
    Mark the given token as revoked.

    Idempotent: if the token is already revoked the existing
    ``revoked_at`` is preserved. Raises nothing if the token does not
    exist; lookups of unknown tokens are a no-op so callers can treat
    revocation as fire-and-forget.
    """
    row = session.get(ApiToken, token_id)
    if row is None or row.revoked_at is not None:
        return
    row.revoked_at = utc_now_iso()
