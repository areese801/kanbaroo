"""
Atomic ``{KEY}-{N}`` allocation.

``generate_human_id`` increments ``workspaces.next_issue_num`` and
returns the previous value formatted as ``{KEY}-{N}``. The allocation
must be safe under concurrent inserts; this test only exercises the
sequential happy path because the Postgres-only locking behavior cannot
be exercised against SQLite.
"""

import pytest
from sqlalchemy.orm import Session

from kanbaroo_core import generate_human_id, models


def test_helper_yields_sequential_ids(session: Session) -> None:
    """
    Calling the helper twice on a fresh workspace yields ``KAN-1`` and
    ``KAN-2`` and leaves ``next_issue_num`` at 3.
    """
    workspace = models.Workspace(key="KAN", name="K")
    session.add(workspace)
    session.commit()

    first = generate_human_id(session, workspace.id)
    second = generate_human_id(session, workspace.id)
    session.commit()

    session.refresh(workspace)
    assert first == "KAN-1"
    assert second == "KAN-2"
    assert workspace.next_issue_num == 3


def test_helper_is_shared_across_stories_and_epics(session: Session) -> None:
    """
    Stories and epics draw from the same counter, so allocating one of
    each yields ``KAN-1`` then ``KAN-2`` regardless of which goes first.
    """
    workspace = models.Workspace(key="KAN", name="K")
    session.add(workspace)
    session.commit()

    epic_id = generate_human_id(session, workspace.id)
    story_id = generate_human_id(session, workspace.id)
    epic = models.Epic(workspace_id=workspace.id, human_id=epic_id, title="E")
    story = models.Story(workspace_id=workspace.id, human_id=story_id, title="S")
    session.add_all([epic, story])
    session.commit()

    assert epic.human_id == "KAN-1"
    assert story.human_id == "KAN-2"


def test_unknown_workspace_raises(session: Session) -> None:
    """
    The helper raises :class:`ValueError` for an unknown workspace id.
    """
    with pytest.raises(ValueError):
        generate_human_id(session, "00000000-0000-7000-8000-000000000000")
