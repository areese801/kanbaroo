"""
Story-tag association table.

This is a pure many-to-many link with no surrogate primary key. Modeled
as a Core :class:`Table` rather than an ORM class because nothing in the
codebase needs to load it as an entity.
"""

from sqlalchemy import Column, ForeignKey, String, Table

from kanbaroo_core.db import Base
from kanbaroo_core.time import utc_now_iso

story_tags = Table(
    "story_tags",
    Base.metadata,
    Column(
        "story_id",
        String,
        ForeignKey("stories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        String,
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("created_at", String, nullable=False, default=utc_now_iso),
)
