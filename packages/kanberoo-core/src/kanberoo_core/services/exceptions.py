"""
Domain exceptions raised by the Kanberoo service layer.

These are deliberately independent of any HTTP or transport concern:
services raise them; the API layer translates them into the wire error
shape defined in ``docs/spec.md`` section 4.1. Keeping the exceptions
transport-free means the CLI, TUI, and (eventually) MCP layers can each
render them in the form they prefer without pulling in FastAPI.
"""

from typing import Any


class ServiceError(Exception):
    """
    Base class for every error raised by the service layer.

    Subclasses carry structured attributes so that the API layer can
    render them into the ``{"error": {"code", "message", "details"}}``
    response shape without string-parsing.
    """

    code: str = "service_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}


class NotFoundError(ServiceError):
    """
    Raised when an entity lookup fails or the entity is soft-deleted.

    ``entity_type`` is the canonical singular noun used in audit rows
    (``workspace``, ``story``, ...). ``entity_id`` is the primary key
    the caller supplied. Both appear in the error details so API clients
    can render a helpful message.
    """

    code = "not_found"

    def __init__(self, entity_type: str, entity_id: str) -> None:
        super().__init__(
            message=f"{entity_type} {entity_id} not found",
            details={"entity_type": entity_type, "entity_id": entity_id},
        )
        self.entity_type = entity_type
        self.entity_id = entity_id


class VersionConflictError(ServiceError):
    """
    Raised when an ``If-Match`` version does not match the stored
    ``version`` on the target row.

    This maps to ``412 Precondition Failed``. Both the caller-supplied
    ``expected`` and the stored ``actual`` appear in the details so a
    TUI or CLI can tell the user what to refetch.
    """

    code = "version_conflict"

    def __init__(
        self,
        entity_type: str,
        entity_id: str,
        expected: int,
        actual: int,
    ) -> None:
        super().__init__(
            message=(
                f"{entity_type} {entity_id} version conflict: "
                f"expected {expected}, actual {actual}"
            ),
            details={
                "entity_type": entity_type,
                "entity_id": entity_id,
                "expected_version": expected,
                "actual_version": actual,
            },
        )
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.expected = expected
        self.actual = actual


class ValidationError(ServiceError):
    """
    Raised for semantic validation beyond what Pydantic catches.

    Pydantic handles shape and type validation at the schema boundary;
    this exception is for errors that require a database lookup or a
    cross-field rule (e.g. a duplicate workspace key).
    """

    code = "validation_error"

    def __init__(self, field: str, message: str) -> None:
        super().__init__(
            message=message,
            details={"field": field},
        )
        self.field = field
