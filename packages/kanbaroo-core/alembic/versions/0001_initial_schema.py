"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-17

This migration creates the full schema documented in ``docs/spec.md``
section 3.3. Enum values are inlined so the migration is self-contained
and survives subsequent reorganizations of the Python enum classes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIVE_PREDICATE = text("deleted_at IS NULL")

_ACTOR_TYPES = ("human", "claude", "system")
_STORY_STATES = ("backlog", "todo", "in_progress", "in_review", "done")
_STORY_PRIORITIES = ("none", "low", "medium", "high")
_EPIC_STATES = ("open", "closed")
_LINK_TYPES = (
    "relates_to",
    "blocks",
    "is_blocked_by",
    "duplicates",
    "is_duplicated_by",
)
_LINK_ENDPOINT_TYPES = ("story", "epic")
_AUDIT_ENTITY_TYPES = (
    "workspace",
    "epic",
    "story",
    "comment",
    "linkage",
    "tag",
)


def upgrade() -> None:
    """
    Create every table, constraint, and index defined in spec section 3.3.
    """

    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("key", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "next_issue_num",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.String(), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )

    op.create_table(
        "workspace_repos",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("repo_url", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("workspace_id", "label", name="uq_workspace_repos_label"),
    )

    op.create_table(
        "epics",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("human_id", sa.String(), nullable=False, unique=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                *_EPIC_STATES,
                name="epic_state",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.String(), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )

    op.create_table(
        "stories",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "epic_id",
            sa.String(),
            sa.ForeignKey("epics.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("human_id", sa.String(), nullable=False, unique=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "priority",
            sa.Enum(
                *_STORY_PRIORITIES,
                name="story_priority",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
            server_default=sa.text("'none'"),
        ),
        sa.Column(
            "state",
            sa.Enum(
                *_STORY_STATES,
                name="story_state",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
            server_default=sa.text("'backlog'"),
        ),
        sa.Column(
            "state_actor_type",
            sa.Enum(
                *_ACTOR_TYPES,
                name="story_state_actor_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("state_actor_id", sa.String(), nullable=True),
        sa.Column("branch_name", sa.String(), nullable=True),
        sa.Column("commit_sha", sa.String(), nullable=True),
        sa.Column("pr_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.String(), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )

    op.create_index(
        "idx_stories_workspace",
        "stories",
        ["workspace_id"],
        sqlite_where=_LIVE_PREDICATE,
        postgresql_where=_LIVE_PREDICATE,
    )
    op.create_index(
        "idx_stories_epic",
        "stories",
        ["epic_id"],
        sqlite_where=_LIVE_PREDICATE,
        postgresql_where=_LIVE_PREDICATE,
    )
    op.create_index(
        "idx_stories_state",
        "stories",
        ["workspace_id", "state"],
        sqlite_where=_LIVE_PREDICATE,
        postgresql_where=_LIVE_PREDICATE,
    )

    op.create_table(
        "linkages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "source_type",
            sa.Enum(
                *_LINK_ENDPOINT_TYPES,
                name="linkage_source_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column(
            "target_type",
            sa.Enum(
                *_LINK_ENDPOINT_TYPES,
                name="linkage_target_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column(
            "link_type",
            sa.Enum(
                *_LINK_TYPES,
                name="link_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.String(), nullable=True),
        sa.UniqueConstraint(
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "link_type",
            name="uq_linkages_endpoints",
        ),
    )

    op.create_index(
        "idx_linkages_source",
        "linkages",
        ["source_type", "source_id"],
        sqlite_where=_LIVE_PREDICATE,
        postgresql_where=_LIVE_PREDICATE,
    )
    op.create_index(
        "idx_linkages_target",
        "linkages",
        ["target_type", "target_id"],
        sqlite_where=_LIVE_PREDICATE,
        postgresql_where=_LIVE_PREDICATE,
    )

    op.create_table(
        "comments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "story_id",
            sa.String(),
            sa.ForeignKey("stories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            sa.String(),
            sa.ForeignKey("comments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column(
            "actor_type",
            sa.Enum(
                *_ACTOR_TYPES,
                name="comment_actor_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.String(), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )

    op.create_index(
        "idx_comments_story",
        "comments",
        ["story_id"],
        sqlite_where=_LIVE_PREDICATE,
        postgresql_where=_LIVE_PREDICATE,
    )

    op.create_table(
        "tags",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("deleted_at", sa.String(), nullable=True),
        sa.UniqueConstraint("workspace_id", "name", name="uq_tags_workspace_name"),
    )

    op.create_table(
        "story_tags",
        sa.Column(
            "story_id",
            sa.String(),
            sa.ForeignKey("stories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.String(),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("created_at", sa.String(), nullable=False),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("occurred_at", sa.String(), nullable=False),
        sa.Column(
            "actor_type",
            sa.Enum(
                *_ACTOR_TYPES,
                name="audit_actor_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column(
            "entity_type",
            sa.Enum(
                *_AUDIT_ENTITY_TYPES,
                name="audit_entity_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("diff", sa.String(), nullable=False),
    )

    op.create_index(
        "idx_audit_entity",
        "audit_events",
        ["entity_type", "entity_id", "occurred_at"],
    )
    op.create_index(
        "idx_audit_actor",
        "audit_events",
        ["actor_type", "actor_id", "occurred_at"],
    )

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column(
            "actor_type",
            sa.Enum(
                *_ACTOR_TYPES,
                name="api_token_actor_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("last_used_at", sa.String(), nullable=True),
        sa.Column("revoked_at", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """
    Drop everything created by :func:`upgrade` in reverse order.
    """
    op.drop_table("api_tokens")
    op.drop_index("idx_audit_actor", table_name="audit_events")
    op.drop_index("idx_audit_entity", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("story_tags")
    op.drop_table("tags")
    op.drop_index("idx_comments_story", table_name="comments")
    op.drop_table("comments")
    op.drop_index("idx_linkages_target", table_name="linkages")
    op.drop_index("idx_linkages_source", table_name="linkages")
    op.drop_table("linkages")
    op.drop_index("idx_stories_state", table_name="stories")
    op.drop_index("idx_stories_epic", table_name="stories")
    op.drop_index("idx_stories_workspace", table_name="stories")
    op.drop_table("stories")
    op.drop_table("epics")
    op.drop_table("workspace_repos")
    op.drop_table("workspaces")
