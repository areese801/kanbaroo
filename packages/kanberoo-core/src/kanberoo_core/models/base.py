"""
Reusable column mixins for Kanberoo models.

These factor out the three cross-cutting patterns called out in
``docs/spec.md`` section 3.4: timestamps, soft delete, and the
optimistic-concurrency ``version`` column. The version column is also
wired up to SQLAlchemy's ``version_id_col`` mechanism on each model that
includes :class:`VersionMixin`, so updates auto-increment it.
"""

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from kanberoo_core.time import utc_now_iso


class TimestampMixin:
    """
    Adds ``created_at`` and ``updated_at`` columns populated by
    :func:`kanberoo_core.time.utc_now_iso`.
    """

    created_at: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=utc_now_iso,
    )
    updated_at: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=utc_now_iso,
        onupdate=utc_now_iso,
    )


class SoftDeleteMixin:
    """
    Adds a nullable ``deleted_at`` column. ``NULL`` means the row is live;
    a timestamp means it was soft-deleted at that instant.
    """

    deleted_at: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        default=None,
    )


class VersionMixin:
    """
    Adds a ``version`` integer column starting at ``1``.

    Each model that mixes this in must also configure
    ``__mapper_args__ = {"version_id_col": cls.version}`` so that
    SQLAlchemy auto-increments the value on every UPDATE and detects
    stale-data conflicts.
    """

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
