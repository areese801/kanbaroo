"""
Epic model.

Epics are optional containers grouping related stories within a workspace.
Epic IDs are drawn from the workspace's shared issue counter, so a given
``KAN-N`` is unique whether it is an epic or a story (see
``docs/spec.md`` section 3.4).
"""

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from kanberoo_core.db import Base, new_id
from kanberoo_core.enums import EpicState
from kanberoo_core.models.base import (
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class Epic(Base, TimestampMixin, SoftDeleteMixin, VersionMixin):
    """
    Optional container for related stories within a workspace.
    """

    __tablename__ = "epics"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    human_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[EpicState] = mapped_column(
        Enum(EpicState, native_enum=False, name="epic_state", create_constraint=True),
        nullable=False,
        default=EpicState.OPEN,
    )

    __mapper_args__ = {"version_id_col": VersionMixin.version}
