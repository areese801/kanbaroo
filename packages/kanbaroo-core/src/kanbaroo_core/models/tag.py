"""
Tag model.

Tags are workspace-scoped: a tag named ``bug`` in workspace A is a
distinct row from ``bug`` in workspace B.
"""

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from kanbaroo_core.db import Base, new_id
from kanbaroo_core.models.base import SoftDeleteMixin
from kanbaroo_core.time import utc_now_iso


class Tag(Base, SoftDeleteMixin):
    """
    A workspace-scoped label that can be attached to stories.
    """

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_tags_workspace_name"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)
