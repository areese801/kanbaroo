"""
Linkage model.

A linkage is a typed, directed relationship between two issues (story-to-
story or story-to-epic). The blocks/is_blocked_by mirroring described in
the spec is service-layer logic and lives in a later milestone; the model
itself just stores the row.
"""

from sqlalchemy import Enum, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from kanberoo_core.db import Base, new_id
from kanberoo_core.enums import LinkEndpointType, LinkType, enum_values
from kanberoo_core.models.base import SoftDeleteMixin
from kanberoo_core.time import utc_now_iso

_LIVE_PREDICATE = text("deleted_at IS NULL")


class Linkage(Base, SoftDeleteMixin):
    """
    A directed, typed link between two issues.
    """

    __tablename__ = "linkages"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "link_type",
            name="uq_linkages_endpoints",
        ),
        Index(
            "idx_linkages_source",
            "source_type",
            "source_id",
            sqlite_where=_LIVE_PREDICATE,
            postgresql_where=_LIVE_PREDICATE,
        ),
        Index(
            "idx_linkages_target",
            "target_type",
            "target_id",
            sqlite_where=_LIVE_PREDICATE,
            postgresql_where=_LIVE_PREDICATE,
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    source_type: Mapped[LinkEndpointType] = mapped_column(
        Enum(
            LinkEndpointType,
            native_enum=False,
            name="linkage_source_type",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    target_type: Mapped[LinkEndpointType] = mapped_column(
        Enum(
            LinkEndpointType,
            native_enum=False,
            name="linkage_target_type",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    target_id: Mapped[str] = mapped_column(String, nullable=False)
    link_type: Mapped[LinkType] = mapped_column(
        Enum(
            LinkType,
            native_enum=False,
            name="link_type",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)
