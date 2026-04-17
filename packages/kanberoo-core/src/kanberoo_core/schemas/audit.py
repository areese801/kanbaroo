"""
Pydantic schema for audit events.

Audit events are immutable, so only a Read schema is defined here. The
write path (``emit_audit``) lives in the service layer and arrives in a
later milestone.
"""

from kanberoo_core.enums import ActorType, AuditEntityType
from kanberoo_core.schemas._base import ReadModel


class AuditEventRead(ReadModel):
    """
    Server response for any audit event read. ``diff`` is a JSON-encoded
    string of ``{"before": ..., "after": ...}``.
    """

    id: str
    occurred_at: str
    actor_type: ActorType
    actor_id: str
    entity_type: AuditEntityType
    entity_id: str
    action: str
    diff: str
