"""
Thin service wrappers around :mod:`kanberoo_core.auth`.

Tokens are explicitly **not** audited: per ``docs/spec.md`` section 3.3
the audit log is reserved for user-visible entities (workspaces, epics,
stories, comments, linkages, tags). Tokens are auth metadata, not
domain entities, and adding a seventh ``AuditEntityType`` just to log
their lifecycle would muddy the external reader contract.

That rule is the whole reason this module exists as a distinct service:
it gives endpoints a consistent call site (always ``services.tokens``)
so future code review can enforce "services are the audit boundary"
without having to special-case auth-adjacent paths.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from kanberoo_core import auth
from kanberoo_core.actor import Actor
from kanberoo_core.models.api_token import ApiToken
from kanberoo_core.schemas.api_token import ApiTokenCreate
from kanberoo_core.services.exceptions import NotFoundError


def create_token_service(
    session: Session,
    *,
    actor: Actor,  # noqa: ARG001 - kept for symmetry with audited services
    payload: ApiTokenCreate,
) -> tuple[ApiToken, str]:
    """
    Issue a new API token and return the row plus its plaintext.

    The ``actor`` parameter is accepted so every service function has
    the same call shape (endpoints always pass it in), but no audit
    event is emitted. Callers must display the returned plaintext to
    the user exactly once; it is unrecoverable afterwards.
    """
    return auth.create_token(
        session,
        actor_type=payload.actor_type,
        actor_id=payload.actor_id,
        name=payload.name,
    )


def list_tokens(
    session: Session,
    *,
    include_revoked: bool = False,
) -> list[ApiToken]:
    """
    Return every API token, newest first.

    Revoked tokens are hidden by default; admin callers that need the
    full history pass ``include_revoked=True``. The plaintext is not
    part of the return value; callers only ever see ``token_hash``.
    """
    stmt = select(ApiToken).order_by(ApiToken.created_at.desc())
    if not include_revoked:
        stmt = stmt.where(ApiToken.revoked_at.is_(None))
    return list(session.execute(stmt).scalars().all())


def revoke_token_service(
    session: Session,
    *,
    actor: Actor,  # noqa: ARG001 - kept for symmetry with audited services
    token_id: str,
) -> None:
    """
    Revoke an API token.

    Idempotent (revoking an already-revoked token is a no-op), matching
    :func:`kanberoo_core.auth.revoke_token`. Raises
    :class:`NotFoundError` if the token id is completely unknown so the
    API returns 404 rather than silently succeeding on typos.
    """
    row = session.get(ApiToken, token_id)
    if row is None:
        raise NotFoundError("api_token", token_id)
    auth.revoke_token(session, token_id)
