"""
Comment model.

Comments are markdown attached to a story. The schema permits one level
of threading via ``parent_id`` (a self-FK); the rule that replies cannot
have replies is enforced by the API layer, not by the database.
"""

from sqlalchemy import Enum, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from kanberoo_core.db import Base, new_id
from kanberoo_core.enums import ActorType
from kanberoo_core.models.base import (
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

_LIVE_PREDICATE = text("deleted_at IS NULL")


class Comment(Base, TimestampMixin, SoftDeleteMixin, VersionMixin):
    """
    A markdown comment on a story. May be a reply to another comment via
    ``parent_id``; replies cannot themselves have replies (enforced
    elsewhere).
    """

    __tablename__ = "comments"
    __table_args__ = (
        Index(
            "idx_comments_story",
            "story_id",
            sqlite_where=_LIVE_PREDICATE,
            postgresql_where=_LIVE_PREDICATE,
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    story_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("stories.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("comments.id", ondelete="CASCADE"),
        nullable=True,
    )
    body: Mapped[str] = mapped_column(String, nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(
            ActorType,
            native_enum=False,
            name="comment_actor_type",
            create_constraint=True,
        ),
        nullable=False,
    )
    actor_id: Mapped[str] = mapped_column(String, nullable=False)

    __mapper_args__ = {"version_id_col": VersionMixin.version}
