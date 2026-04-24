"""
Pydantic schema for audit events.

Audit events are immutable, so only a Read schema is defined here. The
write path (``emit_audit``) lives in the service layer.

The database column stores ``diff`` as a JSON-encoded string; this
schema parses it into a structured ``{"before": ..., "after": ...}``
object so clients receive real JSON rather than an embedded string.
Sidesteps a round of double-JSON-decoding on every consumer.
"""

import json
from typing import Any

from pydantic import field_validator

from kanbaroo_core.enums import ActorType, AuditEntityType
from kanbaroo_core.schemas._base import ReadModel


class AuditEventRead(ReadModel):
    """
    Server response for any audit event read.

    ``diff`` is a structured ``{"before": <dict | null>, "after":
    <dict | null>}`` object. The underlying column is TEXT holding a
    JSON blob; the validator below parses it on construction so API
    consumers do not have to.
    """

    id: str
    occurred_at: str
    actor_type: ActorType
    actor_id: str
    entity_type: AuditEntityType
    entity_id: str
    action: str
    diff: dict[str, Any]

    @field_validator("diff", mode="before")
    @classmethod
    def _parse_diff(cls, value: Any) -> Any:
        """
        Parse the stored JSON string into a dict.

        Leaves dict values alone so the schema can be reused for direct
        construction in tests. Any non-dict, non-string value is passed
        through so Pydantic's own type validation surfaces the error.
        """
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {"before": None, "after": None, "raw": value}
        return value
