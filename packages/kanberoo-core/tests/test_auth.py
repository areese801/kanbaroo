"""
Tests for :mod:`kanberoo_core.auth`: token creation, validation, and
revocation round-trips.

The golden invariant: the plaintext is shown once at creation and is
never again observable from the database; only its hash is. These tests
exercise that contract directly.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from kanberoo_core import ActorType
from kanberoo_core.auth import (
    TOKEN_PREFIX,
    create_token,
    generate_token_plaintext,
    hash_token,
    revoke_token,
    validate_token,
)


def test_create_and_validate_round_trip(session: Session) -> None:
    """
    A freshly-created token validates back to the right actor and the
    stored hash matches the plaintext.
    """
    row, plaintext = create_token(
        session,
        actor_type=ActorType.HUMAN,
        actor_id="adam",
        name="personal",
    )
    session.commit()

    assert plaintext.startswith(TOKEN_PREFIX)
    assert row.token_hash == hash_token(plaintext)

    actor = validate_token(session, plaintext)
    assert actor is not None
    assert actor.type == ActorType.HUMAN
    assert actor.id == "adam"


def test_validate_updates_last_used_at(session: Session) -> None:
    """
    Successful validation stamps ``last_used_at``.
    """
    _row, plaintext = create_token(
        session,
        actor_type=ActorType.HUMAN,
        actor_id="adam",
        name="personal",
    )
    session.commit()

    assert _row.last_used_at is None
    actor = validate_token(session, plaintext)
    session.commit()
    assert actor is not None

    session.refresh(_row)
    assert _row.last_used_at is not None


def test_invalid_plaintext_returns_none(session: Session) -> None:
    """
    An unknown plaintext resolves to ``None`` rather than raising.
    """
    _row, _plaintext = create_token(
        session,
        actor_type=ActorType.HUMAN,
        actor_id="adam",
        name="personal",
    )
    session.commit()

    assert validate_token(session, "kbr_not-a-real-token") is None


def test_revoked_token_validates_as_none(session: Session) -> None:
    """
    Revoking a token makes subsequent validations return ``None``.
    """
    row, plaintext = create_token(
        session,
        actor_type=ActorType.CLAUDE,
        actor_id="outer-claude",
        name="mcp",
    )
    session.commit()

    revoke_token(session, row.id)
    session.commit()

    assert validate_token(session, plaintext) is None


def test_revoke_is_idempotent(session: Session) -> None:
    """
    Revoking an already-revoked token is a no-op; ``revoked_at`` does
    not change on the second call.
    """
    row, _plaintext = create_token(
        session,
        actor_type=ActorType.HUMAN,
        actor_id="adam",
        name="personal",
    )
    session.commit()

    revoke_token(session, row.id)
    session.commit()
    first_revoked_at = row.revoked_at
    assert first_revoked_at is not None

    revoke_token(session, row.id)
    session.commit()
    assert row.revoked_at == first_revoked_at


def test_revoke_unknown_token_is_noop(session: Session) -> None:
    """
    Revoking an id that does not exist does not raise.
    """
    revoke_token(session, "00000000-0000-0000-0000-000000000000")
    session.commit()


def test_generate_plaintext_is_unique() -> None:
    """
    Sanity check: two consecutive calls produce different tokens.

    Not a theorem (collisions are astronomically unlikely, not
    impossible), but catches a trivial bug where the helper returns a
    constant.
    """
    assert generate_token_plaintext() != generate_token_plaintext()


def test_plaintext_is_not_persisted(session: Session) -> None:
    """
    The plaintext must never appear in the database; only its hash
    should. Verify by scanning every column of the api_tokens row for
    an exact match to the plaintext.
    """
    row, plaintext = create_token(
        session,
        actor_type=ActorType.HUMAN,
        actor_id="adam",
        name="personal",
    )
    session.commit()

    result = (
        session.execute(
            text("SELECT * FROM api_tokens WHERE id = :id"),
            {"id": row.id},
        )
        .mappings()
        .one()
    )

    for column, value in result.items():
        assert value != plaintext, f"plaintext token leaked into column {column!r}"

    assert result["token_hash"] == hash_token(plaintext)


def test_hash_is_stable_and_deterministic() -> None:
    """
    The hash helper is a pure function: same input, same output.
    """
    assert hash_token("kbr_abc") == hash_token("kbr_abc")
    assert hash_token("kbr_abc") != hash_token("kbr_def")
