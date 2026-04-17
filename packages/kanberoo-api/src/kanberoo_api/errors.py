"""
The wire error shape and FastAPI exception handlers.

``docs/spec.md`` section 4.1 nails down a single error envelope used by
every endpoint:

.. code-block:: json

    {
      "error": {
        "code": "not_found",
        "message": "Human-readable message",
        "details": { "..." }
      }
    }

This module owns both the Pydantic response model and the FastAPI
exception handlers that translate service-level exceptions and
framework exceptions into that shape. Endpoints are expected to raise
domain exceptions (from :mod:`kanberoo_core.services.exceptions`);
they should not return error payloads directly.
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from kanberoo_core.services.exceptions import (
    NotFoundError,
    ServiceError,
    ValidationError,
    VersionConflictError,
)


class ErrorBody(BaseModel):
    """
    Inner object of the canonical error envelope.
    """

    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """
    Canonical error response shape. Every non-2xx response body is an
    instance of this model.
    """

    error: ErrorBody


def build_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """
    Build a ``JSONResponse`` carrying the canonical error envelope.
    """
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details)
    ).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=body)


def _handle_not_found(_request: Request, exc: Exception) -> JSONResponse:
    """
    Translate :class:`NotFoundError` into a 404 response.
    """
    assert isinstance(exc, NotFoundError)
    return build_error_response(
        status_code=status.HTTP_404_NOT_FOUND,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


def _handle_version_conflict(_request: Request, exc: Exception) -> JSONResponse:
    """
    Translate :class:`VersionConflictError` into a 412 response.
    """
    assert isinstance(exc, VersionConflictError)
    return build_error_response(
        status_code=status.HTTP_412_PRECONDITION_FAILED,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


def _handle_validation(_request: Request, exc: Exception) -> JSONResponse:
    """
    Translate service-level :class:`ValidationError` into a 400 response.
    """
    assert isinstance(exc, ValidationError)
    return build_error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


def _handle_service(_request: Request, exc: Exception) -> JSONResponse:
    """
    Fallback for any :class:`ServiceError` subclass that does not have
    its own handler. Returns 400 by default to keep the contract
    predictable; add a dedicated handler above if a subclass needs a
    different status.
    """
    assert isinstance(exc, ServiceError)
    return build_error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


def _handle_http(_request: Request, exc: Exception) -> JSONResponse:
    """
    Translate ``HTTPException`` (used by the auth dependency) into the
    canonical envelope.

    FastAPI's default handler returns ``{"detail": "..."}`` which is
    inconsistent with the spec's error shape; this handler forces every
    HTTP error to use the canonical envelope. ``exc.detail`` is allowed
    to be a dict with pre-shaped error content or a plain string.
    """
    assert isinstance(exc, StarletteHTTPException)
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        code = str(detail["code"])
        message = str(detail["message"])
        details = detail.get("details")
        details_dict: dict[str, Any] | None = (
            dict(details) if isinstance(details, dict) else None
        )
    else:
        code = _default_code_for_status(exc.status_code)
        message = (
            str(detail) if detail else _default_message_for_status(exc.status_code)
        )
        details_dict = None
    return build_error_response(
        status_code=exc.status_code,
        code=code,
        message=message,
        details=details_dict,
    )


def _handle_request_validation(_request: Request, exc: Exception) -> JSONResponse:
    """
    Translate Pydantic validation errors on request parsing into a 400
    with the canonical envelope.
    """
    assert isinstance(exc, RequestValidationError)
    return build_error_response(
        status_code=status.HTTP_400_BAD_REQUEST,
        code="validation_error",
        message="request body failed validation",
        details={"errors": exc.errors()},
    )


def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
    """
    Fallback for any uncaught exception. Logs and returns a 500.

    Endpoints should never rely on this path; it exists so the wire
    contract still holds if business logic forgets to convert an error.
    """
    return build_error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
        message=f"unexpected server error: {exc.__class__.__name__}",
        details=None,
    )


def _default_code_for_status(status_code: int) -> str:
    """
    Pick a sensible error ``code`` for an ``HTTPException`` that did not
    carry one explicitly.
    """
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return "unauthorized"
    if status_code == status.HTTP_403_FORBIDDEN:
        return "forbidden"
    if status_code == status.HTTP_404_NOT_FOUND:
        return "not_found"
    if status_code == status.HTTP_412_PRECONDITION_FAILED:
        return "version_conflict"
    if 400 <= status_code < 500:
        return "bad_request"
    return "internal_error"


def _default_message_for_status(status_code: int) -> str:
    """
    Pick a sensible fallback message for an ``HTTPException`` without
    a useful ``detail``.
    """
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return "authentication required"
    if status_code == status.HTTP_404_NOT_FOUND:
        return "not found"
    return "request could not be processed"


def register_exception_handlers(app: FastAPI) -> None:
    """
    Attach every Kanberoo error handler to ``app``.

    Called once by :func:`kanberoo_api.app.create_app` at startup. Order
    matters only insofar as more-specific handlers must be registered
    before their parent classes; FastAPI dispatches by exact type.
    """
    app.add_exception_handler(NotFoundError, _handle_not_found)
    app.add_exception_handler(VersionConflictError, _handle_version_conflict)
    app.add_exception_handler(ValidationError, _handle_validation)
    app.add_exception_handler(ServiceError, _handle_service)
    app.add_exception_handler(StarletteHTTPException, _handle_http)
    app.add_exception_handler(RequestValidationError, _handle_request_validation)
    app.add_exception_handler(Exception, _handle_unexpected)
