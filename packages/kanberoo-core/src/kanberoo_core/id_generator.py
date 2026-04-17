"""
Atomic human-readable ID allocation.

Stories and epics share a single monotonic counter per workspace
(``workspaces.next_issue_num``). Allocating an ID bumps that counter and
returns ``{KEY}-{N}``. The allocation must be atomic so two concurrent
inserts never collide; see ``docs/spec.md`` section 3.4.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from kanberoo_core.models.workspace import Workspace


def generate_human_id(session: Session, workspace_id: str) -> str:
    """
    Allocate the next ``{KEY}-{N}`` identifier for a workspace.

    Reads the workspace row with ``SELECT ... FOR UPDATE`` (a no-op on
    SQLite, where there is at most one writer at a time, and a row-level
    lock on Postgres), increments ``next_issue_num``, flushes the change,
    and returns the allocated identifier. The caller must commit the
    enclosing transaction for the increment to persist.

    Raises :class:`ValueError` if ``workspace_id`` does not exist.
    """
    workspace = session.execute(
        select(Workspace).where(Workspace.id == workspace_id).with_for_update()
    ).scalar_one_or_none()
    if workspace is None:
        raise ValueError(f"workspace not found: {workspace_id}")
    issued = workspace.next_issue_num
    workspace.next_issue_num = issued + 1
    session.flush()
    return f"{workspace.key}-{issued}"
