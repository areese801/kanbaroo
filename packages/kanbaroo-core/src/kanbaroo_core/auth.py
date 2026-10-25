"""
Token creation, hashing, and validation helpers.

These primitives are the bottom half of the auth layer. The top half
(the FastAPI ``Authorization: Bearer`` dependency that turns a request
into an :class:`~kanbaroo_core.actor.Actor`) lands in milestone 4 with
the rest of the API scaffold.

Conventions (see ``docs/spec.md`` sections 3.3 and 4.1):

- Plaintext tokens are ``kbr_``-prefixed, URL-safe random strings. The
  prefix makes them grep-able in logs and distinguishable from other
  opaque IDs.
- The database only ever stores the SHA-256 hex digest in
  ``api_tokens.token_hash``. The plaintext is shown to the caller
  exactly once, at creation time, and is never recoverable afterwards.
- Validation refreshes ``last_used_at`` on success so that idle tokens
  are identifiable. The stamp is throttled to once per
  :data:`LAST_USED_AT_REFRESH_SECONDS` so a burst of authenticated
  reads does not turn every GET into a write transaction (SQLite
  serializes writers, which was measurably slowing concurrent reads).
- Revocation is idempotent: revoking an already-revoked token is a
  no-op.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from kanbaroo_core.actor import Actor
from kanbaroo_core.enums import ActorType
from kanbaroo_core.models.api_token import ApiToken
from kanbaroo_core.time import format_utc_iso, parse_utc_iso, utc_now_iso

TOKEN_PREFIX = "kbr_"

# Minimum age of ``last_used_at`` before a successful validation
# rewrites it. Coarse on purpose: the column answers "is this token
# idle?", which does not need sub-minute precision.
LAST_USED_AT_REFRESH_SECONDS = 60


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
    URL-safe base64 and prefixed with ``kbr_`` so it is recognizable if
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


def _should_refresh_last_used(previous: str | None, now: datetime) -> bool:
    """
    Return ``True`` when ``last_used_at`` is missing, unparseable, or
    older than :data:`LAST_USED_AT_REFRESH_SECONDS` relative to ``now``.

    An unparseable stored value counts as stale so a hand-edited or
    corrupted row heals itself on the next successful validation.
    """
    parsed = parse_utc_iso(previous)
    if parsed is None:
        return True
    return now - parsed >= timedelta(seconds=LAST_USED_AT_REFRESH_SECONDS)


def validate_token(
    session: Session,
    plaintext: str,
    *,
    now: datetime | None = None,
) -> Actor | None:
    """
    Resolve a plaintext token to its :class:`Actor`, or ``None``.

    Hashes the candidate, looks up the matching row, and returns the
    attributed actor. Returns ``None`` if the hash is unknown or the
    token has been revoked.

    On success, refreshes ``last_used_at`` only when it is ``NULL`` or
    at least :data:`LAST_USED_AT_REFRESH_SECONDS` old, so the common
    case (a client issuing many requests in quick succession) is a
    pure read and leaves the session clean. Callers commit the
    surrounding transaction when a refresh did happen. ``now`` exists
    so tests can freeze time; production callers leave it ``None``.
    """
    digest = hash_token(plaintext)
    row = session.execute(
        select(ApiToken).where(ApiToken.token_hash == digest)
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    current = now if now is not None else datetime.now(UTC)
    if _should_refresh_last_used(row.last_used_at, current):
        row.last_used_at = format_utc_iso(current)
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
