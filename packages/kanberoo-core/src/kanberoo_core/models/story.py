"""
Story model.

Stories are the unit of work in Kanberoo and map mentally to a single
pull request. Their lifecycle (``backlog`` -> ``done``) is documented in
``docs/spec.md`` section 4.3 and enforced at the database layer with a
CHECK constraint via ``Enum(StoryState, native_enum=False)``.
"""

from sqlalchemy import Enum, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from kanberoo_core.db import Base, new_id
from kanberoo_core.enums import ActorType, StoryPriority, StoryState, enum_values
from kanberoo_core.models.base import (
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

_LIVE_PREDICATE = text("deleted_at IS NULL")


class Story(Base, TimestampMixin, SoftDeleteMixin, VersionMixin):
    """
    A single unit of work. Belongs to a workspace and optionally to an
    epic within that workspace.
    """

    __tablename__ = "stories"
    __table_args__ = (
        Index(
            "idx_stories_workspace",
            "workspace_id",
            sqlite_where=_LIVE_PREDICATE,
            postgresql_where=_LIVE_PREDICATE,
        ),
        Index(
            "idx_stories_epic",
            "epic_id",
            sqlite_where=_LIVE_PREDICATE,
            postgresql_where=_LIVE_PREDICATE,
        ),
        Index(
            "idx_stories_state",
            "workspace_id",
            "state",
            sqlite_where=_LIVE_PREDICATE,
            postgresql_where=_LIVE_PREDICATE,
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    epic_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("epics.id", ondelete="SET NULL"),
        nullable=True,
    )
    human_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    priority: Mapped[StoryPriority] = mapped_column(
        Enum(
            StoryPriority,
            native_enum=False,
            name="story_priority",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
        default=StoryPriority.NONE,
    )
    state: Mapped[StoryState] = mapped_column(
        Enum(
            StoryState,
            native_enum=False,
            name="story_state",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=False,
        default=StoryState.BACKLOG,
    )
    state_actor_type: Mapped[ActorType | None] = mapped_column(
        Enum(
            ActorType,
            native_enum=False,
            name="story_state_actor_type",
            create_constraint=True,
            values_callable=enum_values,
        ),
        nullable=True,
    )
    state_actor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String, nullable=True)

    __mapper_args__ = {"version_id_col": VersionMixin.version}
