"""
Token REST endpoints.

Tokens are the only resource in v1 that is **not** audited: per
``docs/spec.md`` section 3.3, auth metadata is outside the audit entity
type enum. Listing is masked (only ``token_hash`` is exposed, never
plaintext); creation returns the plaintext exactly once.
"""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from kanbaroo_api.auth import resolve_actor
from kanbaroo_api.db import get_session
from kanbaroo_core.actor import Actor
from kanbaroo_core.schemas.api_token import (
    ApiTokenCreate,
    ApiTokenCreatedRead,
    ApiTokenRead,
)
from kanbaroo_core.services import tokens as token_service

router = APIRouter(prefix="/tokens", tags=["tokens"])


@router.get("", response_model=list[ApiTokenRead])
def list_tokens(
    include_revoked: bool = Query(False),
    session: Session = Depends(get_session),
    _actor: Actor = Depends(resolve_actor),
) -> list[ApiTokenRead]:
    """
    Return every API token as a masked read model (``token_hash`` only,
    no plaintext).
    """
    rows = token_service.list_tokens(session, include_revoked=include_revoked)
    return [ApiTokenRead.model_validate(row) for row in rows]


@router.post(
    "",
    response_model=ApiTokenCreatedRead,
    status_code=status.HTTP_201_CREATED,
)
def create_token(
    payload: ApiTokenCreate,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> ApiTokenCreatedRead:
    """
    Issue a new token and return it with its plaintext.

    The plaintext appears in this response body only; all subsequent
    reads of the same row return :class:`ApiTokenRead` without it. The
    client is responsible for storing it securely.
    """
    row, plaintext = token_service.create_token_service(
        session,
        actor=actor,
        payload=payload,
    )
    base = ApiTokenRead.model_validate(row).model_dump(mode="json")
    return ApiTokenCreatedRead.model_validate({**base, "plaintext": plaintext})


@router.delete(
    "/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def revoke_token(
    token_id: str,
    session: Session = Depends(get_session),
    actor: Actor = Depends(resolve_actor),
) -> Response:
    """
    Revoke a token. Idempotent: revoking an already-revoked token is a
    204. An unknown id is a 404.
    """
    token_service.revoke_token_service(session, actor=actor, token_id=token_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
