"""
Pydantic schemas for workspaces and the repos attached to them.
"""

from kanberoo_core.schemas._base import ReadModel, WriteModel


class WorkspaceCreate(WriteModel):
    """
    Payload for ``POST /workspaces``. ``key`` is the short prefix used for
    human IDs (``KAN``, ``ENG``, ...).
    """

    key: str
    name: str
    description: str | None = None


class WorkspaceUpdate(WriteModel):
    """
    Payload for ``PATCH /workspaces/{id}``.

    ``key`` is intentionally omitted: re-keying a workspace would
    invalidate every previously-issued human ID.
    """

    name: str | None = None
    description: str | None = None


class WorkspaceRead(ReadModel):
    """
    Server response for any workspace read.
    """

    id: str
    key: str
    name: str
    description: str | None
    next_issue_num: int
    created_at: str
    updated_at: str
    deleted_at: str | None
    version: int


class WorkspaceRepoCreate(WriteModel):
    """
    Payload for ``POST /workspaces/{id}/repos``.
    """

    label: str
    repo_url: str


class WorkspaceRepoRead(ReadModel):
    """
    Server response for any workspace-repo read.
    """

    id: str
    workspace_id: str
    label: str
    repo_url: str
    created_at: str
