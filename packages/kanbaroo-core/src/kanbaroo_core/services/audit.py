"""
Audit event emission and read-side queries.

:func:`emit_audit` is the write path every service mutation ends with.
The helper writes an :class:`~kanbaroo_core.models.audit.AuditEvent`
row inside the caller's transaction so the audit record lives or dies
with the mutation it describes. It never commits; the calling service
controls transaction boundaries.

The stored ``diff`` is a JSON-encoded object of the shape
``{"before": <dict or null>, "after": <dict or null>}``. Both halves
are stored in full, without field-level minimisation: the audit log is
meant to be readable by external tools (DuckDB, Snowflake) without
needing application-layer knowledge to interpret it, and disk is cheap
compared to the cost of reconstructing history from a lossy diff.

:func:`list_audit` and :func:`list_audit_for_entity` are the read-side
entry points behind ``GET /audit`` and
``GET /audit/entity/{type}/{id}``. They return events newest-first and
paginate with an opaque cursor wrapping the last ``(occurred_at, id)``
pair; ties on ``occurred_at`` are broken by ``id`` so the cursor is
stable even when events land in the same millisecond.
"""

import base64
import json
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from kanbaroo_core.actor import Actor
from kanbaroo_core.enums import ActorType, AuditAction, AuditEntityType
from kanbaroo_core.models.audit import AuditEvent
from kanbaroo_core.services.exceptions import ValidationError
from kanbaroo_core.time import utc_now_iso

DEFAULT_AUDIT_LIMIT = 50
MAX_AUDIT_LIMIT = 200


def emit_audit(
    session: Session,
    *,
    actor: Actor,
    entity_type: AuditEntityType,
    entity_id: str,
    action: AuditAction | str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> AuditEvent:
    """
    Record a mutation in ``audit_events`` and return the new row.

    ``before`` and ``after`` are plain dictionaries (callers typically
    pass ``Model.model_dump(mode="json")`` on a Pydantic schema). Either
    may be ``None``: ``before`` is ``None`` for creates, ``after`` is
    ``None`` for hard deletes (not used today), and both are populated
    for updates and soft deletes.

    The row is added to the session and flushed so its server-side
    defaults (PK) populate, but the transaction is left open for the
    calling service to commit.
    """
    action_value = action.value if isinstance(action, AuditAction) else action
    diff_payload = {"before": before, "after": after}
    event = AuditEvent(
        occurred_at=utc_now_iso(),
        actor_type=actor.type,
        actor_id=actor.id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action_value,
        diff=json.dumps(diff_payload, sort_keys=True),
    )
    session.add(event)
    session.flush()
    return event


def _encode_audit_cursor(occurred_at: str, audit_id: str) -> str:
    """
    Encode ``(occurred_at, id)`` as an opaque cursor.

    The separator is the NUL byte because ``occurred_at`` values never
    contain NUL and the pair reads back unambiguously. Base64 wrapping
    signals that clients should treat the value as opaque.
    """
    raw = f"{occurred_at}\x00{audit_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_audit_cursor(cursor: str) -> tuple[str, str]:
    """
    Decode an audit cursor back into ``(occurred_at, id)``.

    Raises :class:`ValidationError` on any decoding or shape error; the
    API layer renders that as a 400 validation_error.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("cursor", "malformed cursor value") from exc
    if "\x00" not in raw:
        raise ValidationError("cursor", "malformed cursor value")
    occurred_at, _, audit_id = raw.partition("\x00")
    if not occurred_at or not audit_id:
        raise ValidationError("cursor", "malformed cursor value")
    return occurred_at, audit_id


def _parse_audit_event_type(value: str | AuditEntityType) -> AuditEntityType:
    """
    Coerce a free-form entity-type string into :class:`AuditEntityType`.

    Raises :class:`ValidationError` on unknown values rather than the
    default ``ValueError`` so the API layer renders a clean error body.
    """
    if isinstance(value, AuditEntityType):
        return value
    try:
        return AuditEntityType(value)
    except ValueError as exc:
        raise ValidationError(
            "entity_type",
            f"unknown audit entity_type {value!r}",
        ) from exc


def _parse_audit_actor_type(value: str | ActorType) -> ActorType:
    """
    Coerce a free-form actor-type string into :class:`ActorType`.
    """
    if isinstance(value, ActorType):
        return value
    try:
        return ActorType(value)
    except ValueError as exc:
        raise ValidationError(
            "actor_type",
            f"unknown actor_type {value!r}",
        ) from exc


def list_audit(
    session: Session,
    *,
    entity_type: str | AuditEntityType | None = None,
    entity_id: str | None = None,
    actor_type: str | ActorType | None = None,
    actor_id: str | None = None,
    since: str | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_AUDIT_LIMIT,
) -> tuple[list[AuditEvent], str | None]:
    """
    Return a page of audit events newest-first, plus a next cursor.

    Every filter is optional and combines with AND semantics. ``since``
    accepts an ISO 8601 timestamp and returns rows strictly newer than
    that value. The cursor wraps ``(occurred_at, id)`` so pagination is
    stable under ties; a ``None`` cursor means the most recent page.
    ``limit`` is clamped to ``[1, MAX_AUDIT_LIMIT]``.
    """
    if limit < 1:
        limit = 1
    if limit > MAX_AUDIT_LIMIT:
        limit = MAX_AUDIT_LIMIT

    stmt = select(AuditEvent).order_by(
        AuditEvent.occurred_at.desc(),
        AuditEvent.id.desc(),
    )
    if entity_type is not None:
        resolved_entity = _parse_audit_event_type(entity_type)
        stmt = stmt.where(AuditEvent.entity_type == resolved_entity)
    if entity_id is not None:
        stmt = stmt.where(AuditEvent.entity_id == entity_id)
    if actor_type is not None:
        stmt = stmt.where(AuditEvent.actor_type == _parse_audit_actor_type(actor_type))
    if actor_id is not None:
        stmt = stmt.where(AuditEvent.actor_id == actor_id)
    if since is not None:
        stmt = stmt.where(AuditEvent.occurred_at > since)
    if cursor is not None:
        cursor_time, cursor_id = _decode_audit_cursor(cursor)
        stmt = stmt.where(
            or_(
                AuditEvent.occurred_at < cursor_time,
                and_(
                    AuditEvent.occurred_at == cursor_time,
                    AuditEvent.id < cursor_id,
                ),
            )
        )
    stmt = stmt.limit(limit + 1)

    rows = list(session.execute(stmt).scalars().all())
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        tail = rows[-1]
        next_cursor = _encode_audit_cursor(tail.occurred_at, tail.id)
    return rows, next_cursor


def list_audit_for_entity(
    session: Session,
    *,
    entity_type: str | AuditEntityType,
    entity_id: str,
    cursor: str | None = None,
    limit: int = DEFAULT_AUDIT_LIMIT,
) -> tuple[list[AuditEvent], str | None]:
    """
    Return a page of audit events scoped to a single entity.

    Convenience wrapper over :func:`list_audit`. Exposed as its own
    function so the router can mount ``GET /audit/entity/{type}/{id}``
    without having clients construct dual filters themselves.
    """
    return list_audit(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        cursor=cursor,
        limit=limit,
    )
