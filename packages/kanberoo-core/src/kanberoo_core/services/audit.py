"""
Audit event emission.

Every mutation in Kanberoo ends with a call to :func:`emit_audit`. The
helper writes an :class:`~kanberoo_core.models.audit.AuditEvent` row
inside the caller's transaction so the audit record lives or dies with
the mutation it describes. It never commits; the calling service
controls transaction boundaries.

The stored ``diff`` is a JSON-encoded object of the shape
``{"before": <dict or null>, "after": <dict or null>}``. Both halves
are stored in full, without field-level minimisation: the audit log is
meant to be readable by external tools (DuckDB, Snowflake) without
needing application-layer knowledge to interpret it, and disk is cheap
compared to the cost of reconstructing history from a lossy diff.
"""

import json
from typing import Any

from sqlalchemy.orm import Session

from kanberoo_core.actor import Actor
from kanberoo_core.enums import AuditAction, AuditEntityType
from kanberoo_core.models.audit import AuditEvent
from kanberoo_core.time import utc_now_iso


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
