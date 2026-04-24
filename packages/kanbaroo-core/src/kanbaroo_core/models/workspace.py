"""
Workspace and WorkspaceRepo models.

A workspace is the top-level container in Kanbaroo and owns the shared
``next_issue_num`` counter that stories and epics draw from when their
human IDs are allocated (see ``docs/spec.md`` section 3.4).
"""

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from kanbaroo_core.db import Base, new_id
from kanbaroo_core.models.base import (
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)
from kanbaroo_core.time import utc_now_iso


class Workspace(Base, TimestampMixin, SoftDeleteMixin, VersionMixin):
    """
    Top-level workspace. Roughly "a product" or "a consulting engagement".
    """

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    next_issue_num: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": VersionMixin.version}


class WorkspaceRepo(Base):
    """
    A git repository attached to a workspace.

    Workspaces may have any number of repos. The (workspace_id, label)
    pair is unique so each label disambiguates the repo within its
    workspace.
    """

    __tablename__ = "workspace_repos"
    __table_args__ = (
        UniqueConstraint("workspace_id", "label", name="uq_workspace_repos_label"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String, nullable=False)
    repo_url: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False, default=utc_now_iso)
