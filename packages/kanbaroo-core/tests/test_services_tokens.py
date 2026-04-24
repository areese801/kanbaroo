"""
Service-layer tests for tokens.

The single most important invariant here is the **negative** one:
token operations emit no audit rows. That's what distinguishes tokens
from the other service modules and it is the reason the tokens service
exists as a separate call site (see the module docstring).
"""

import pytest
from sqlalchemy.orm import Session

from kanbaroo_core import Actor, ActorType
from kanbaroo_core.auth import hash_token
from kanbaroo_core.models.api_token import ApiToken
from kanbaroo_core.models.audit import AuditEvent
from kanbaroo_core.schemas.api_token import ApiTokenCreate
from kanbaroo_core.services import tokens as token_service
from kanbaroo_core.services.exceptions import NotFoundError

HUMAN = Actor(type=ActorType.HUMAN, id="adam")


def test_create_token_service_returns_row_and_plaintext(session: Session) -> None:
    """
    The wrapper delegates to :func:`kanbaroo_core.auth.create_token` and
    returns the same ``(row, plaintext)`` tuple.
    """
    row, plaintext = token_service.create_token_service(
        session,
        actor=HUMAN,
        payload=ApiTokenCreate(
            actor_type=ActorType.CLAUDE,
            actor_id="outer-claude",
            name="mcp",
        ),
    )
    session.commit()

    assert plaintext.startswith("kbr_")
    assert row.token_hash == hash_token(plaintext)
    assert row.actor_type == ActorType.CLAUDE
    assert row.actor_id == "outer-claude"
    assert row.name == "mcp"


def test_create_token_service_does_not_emit_audit(session: Session) -> None:
    """
    Tokens are not audited. Creating one leaves ``audit_events`` empty.
    """
    token_service.create_token_service(
        session,
        actor=HUMAN,
        payload=ApiTokenCreate(
            actor_type=ActorType.HUMAN,
            actor_id="adam",
            name="personal",
        ),
    )
    session.commit()
    assert session.query(AuditEvent).count() == 0


def test_list_tokens_filters_revoked(session: Session) -> None:
    """
    Revoked tokens are hidden by default and shown when asked for.
    """
    kept, _ = token_service.create_token_service(
        session,
        actor=HUMAN,
        payload=ApiTokenCreate(
            actor_type=ActorType.HUMAN, actor_id="adam", name="kept"
        ),
    )
    gone, _ = token_service.create_token_service(
        session,
        actor=HUMAN,
        payload=ApiTokenCreate(
            actor_type=ActorType.HUMAN, actor_id="adam", name="gone"
        ),
    )
    session.commit()

    token_service.revoke_token_service(
        session,
        actor=HUMAN,
        token_id=gone.id,
    )
    session.commit()

    default_rows = token_service.list_tokens(session)
    assert [r.id for r in default_rows] == [kept.id]

    all_rows = token_service.list_tokens(session, include_revoked=True)
    assert {r.id for r in all_rows} == {kept.id, gone.id}


def test_revoke_token_service_does_not_emit_audit(session: Session) -> None:
    """
    Token revocation also leaves ``audit_events`` empty.
    """
    row, _ = token_service.create_token_service(
        session,
        actor=HUMAN,
        payload=ApiTokenCreate(
            actor_type=ActorType.HUMAN, actor_id="adam", name="personal"
        ),
    )
    session.commit()

    token_service.revoke_token_service(session, actor=HUMAN, token_id=row.id)
    session.commit()
    assert session.query(AuditEvent).count() == 0


def test_revoke_unknown_token_raises_not_found(session: Session) -> None:
    """
    Revoking a totally unknown id raises :class:`NotFoundError` so
    typos surface as 404 rather than silent success.
    """
    with pytest.raises(NotFoundError):
        token_service.revoke_token_service(
            session,
            actor=HUMAN,
            token_id="00000000-0000-0000-0000-000000000000",
        )


def test_revoke_is_idempotent(session: Session) -> None:
    """
    Revoking an already-revoked token is a no-op with no audit.
    """
    row, _ = token_service.create_token_service(
        session,
        actor=HUMAN,
        payload=ApiTokenCreate(
            actor_type=ActorType.HUMAN, actor_id="adam", name="personal"
        ),
    )
    session.commit()

    token_service.revoke_token_service(session, actor=HUMAN, token_id=row.id)
    session.commit()
    original_revoked_at = row.revoked_at

    token_service.revoke_token_service(session, actor=HUMAN, token_id=row.id)
    session.commit()
    session.refresh(row)
    assert row.revoked_at == original_revoked_at
    assert session.query(AuditEvent).count() == 0


def test_tokens_service_roundtrip_query(session: Session) -> None:
    """
    Sanity: after create and revoke, ``api_tokens`` has the expected
    row count regardless of the audit assertions above.
    """
    token_service.create_token_service(
        session,
        actor=HUMAN,
        payload=ApiTokenCreate(actor_type=ActorType.HUMAN, actor_id="adam", name="t1"),
    )
    token_service.create_token_service(
        session,
        actor=HUMAN,
        payload=ApiTokenCreate(
            actor_type=ActorType.CLAUDE, actor_id="outer-claude", name="t2"
        ),
    )
    session.commit()
    assert session.query(ApiToken).count() == 2
