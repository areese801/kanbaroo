"""
Optimistic-concurrency invariants.

Every mutable entity must:

* default ``version`` to 1 on insert,
* increment ``version`` on every update.

The increment is driven by SQLAlchemy's ``version_id_col`` mechanism,
configured on each :class:`VersionMixin`-using model.
"""

from sqlalchemy.orm import Session

from kanberoo_core import models


def test_workspace_version_defaults_to_one(session: Session) -> None:
    """
    A freshly inserted workspace has ``version == 1``.
    """
    workspace = models.Workspace(key="KAN", name="Kanberoo")
    session.add(workspace)
    session.commit()
    assert workspace.version == 1


def test_workspace_version_increments_on_update(session: Session) -> None:
    """
    Updating any field on a workspace bumps its ``version``.
    """
    workspace = models.Workspace(key="KAN", name="Kanberoo")
    session.add(workspace)
    session.commit()

    workspace.name = "Kanberoo Renamed"
    session.commit()
    session.refresh(workspace)
    assert workspace.version == 2

    workspace.description = "More words."
    session.commit()
    session.refresh(workspace)
    assert workspace.version == 3


def test_story_version_increments_on_update(session: Session) -> None:
    """
    The version invariant holds for stories as well as workspaces.
    """
    workspace = models.Workspace(key="KAN", name="Kanberoo")
    session.add(workspace)
    session.flush()
    story = models.Story(workspace_id=workspace.id, human_id="KAN-1", title="First")
    session.add(story)
    session.commit()
    assert story.version == 1

    story.title = "First (renamed)"
    session.commit()
    session.refresh(story)
    assert story.version == 2
