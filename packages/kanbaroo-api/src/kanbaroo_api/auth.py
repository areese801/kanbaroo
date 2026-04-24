"""
FastAPI dependency that resolves ``Authorization: Bearer`` into an
:class:`~kanbaroo_core.actor.Actor`.

Validation happens in :mod:`kanbaroo_core.auth` so the CLI and MCP
layers can reuse it; this module is purely the HTTP adapter. Failures
raise ``HTTPException`` carrying the canonical error shape that
:mod:`kanbaroo_api.errors` picks up.
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from kanbaroo_api.db import get_session
from kanbaroo_core.actor import Actor
from kanbaroo_core.auth import validate_token

BEARER_PREFIX = "Bearer "


def _unauthorized(message: str) -> HTTPException:
    """
    Build a 401 ``HTTPException`` whose detail is the wire error body.

    The custom-handler in :mod:`kanbaroo_api.errors` unwraps this into
    the canonical response shape.
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "unauthorized",
            "message": message,
            "details": None,
        },
        headers={"WWW-Authenticate": "Bearer"},
    )


def resolve_actor(
    request: Request,
    session: Session = Depends(get_session),
) -> Actor:
    """
    Read the ``Authorization`` header, validate the token, return the
    attributed actor.

    Rejects missing headers, malformed headers (anything not starting
    with ``Bearer ``), and unknown or revoked tokens with 401. On
    success, stashes the actor on ``request.state.actor`` so request
    logging and other middleware can pick it up without re-validating.
    """
    header = request.headers.get("authorization")
    if not header:
        raise _unauthorized("missing Authorization header")
    if not header.startswith(BEARER_PREFIX):
        raise _unauthorized("Authorization header must use the Bearer scheme")

    plaintext = header[len(BEARER_PREFIX) :].strip()
    if not plaintext:
        raise _unauthorized("empty bearer token")

    actor = validate_token(session, plaintext)
    if actor is None:
        raise _unauthorized("invalid or revoked token")

    request.state.actor = actor
    return actor
