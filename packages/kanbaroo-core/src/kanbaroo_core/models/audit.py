"""
Audit event model.

Audit events are immutable: once written, they are never updated or
deleted. The model intentionally has no ``version``, ``updated_at``, or
``deleted_at`` columns. Emission of audit events lives in the (future)
service layer; this milestone only defines the table.
"""

from sqlalchemy import Enum, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from kanbaroo_core.db import Base, new_id
from kanbaroo_core.enums import ActorType, AuditEntityType, enum_values
from kanbaroo_core.time import utc_now_iso


class AuditEvent(Base):
    """
    An immutable record of a single mutation. ``diff`` stores a JSON
    blob of ``{"before": ..., "after": ...}`` as TEXT.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index(
            "idx_audit_entity",
            "entity_type",
            "entity_id",
            "occurred_at",
        ),
        Index(
            "idx_audit_actor",
            "actor_type",
            "actor_id",
            "occurred_at",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    occurred_at: Mapped[str] = mapped_column(
        String, nullable=False, default=utc_now_iso
    )
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(
            ActorType,
            native_enum=False,
            name="audit_actor_type",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[AuditEntityType] = mapped_column(
        Enum(
            AuditEntityType,
            native_enum=False,
            name="audit_entity_type",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    entity_id: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    diff: Mapped[str] = mapped_column(String, nullable=False)
