"""
Verify every UNIQUE constraint declared in spec section 3.3.

The constraints live in the database itself; if any are missing, callers
will discover collisions only at insert time, which is exactly what the
DDL is meant to prevent.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kanberoo_core import models


def test_workspace_key_is_unique(session: Session) -> None:
    """
    Two workspaces cannot share a ``key`` prefix.
    """
    session.add(models.Workspace(key="KAN", name="A"))
    session.commit()
    session.add(models.Workspace(key="KAN", name="B"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_story_human_id_is_unique(session: Session) -> None:
    """
    Two stories cannot share a ``human_id``.
    """
    workspace = models.Workspace(key="KAN", name="K")
    session.add(workspace)
    session.flush()
    session.add(models.Story(workspace_id=workspace.id, human_id="KAN-1", title="A"))
    session.commit()
    session.add(models.Story(workspace_id=workspace.id, human_id="KAN-1", title="B"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_epic_human_id_is_unique(session: Session) -> None:
    """
    Two epics cannot share a ``human_id``.
    """
    workspace = models.Workspace(key="KAN", name="K")
    session.add(workspace)
    session.flush()
    session.add(models.Epic(workspace_id=workspace.id, human_id="KAN-1", title="A"))
    session.commit()
    session.add(models.Epic(workspace_id=workspace.id, human_id="KAN-1", title="B"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_tag_name_is_unique_within_workspace(session: Session) -> None:
    """
    Two tags in one workspace cannot share a ``name`` (composite UNIQUE
    on ``(workspace_id, name)``); the same name in a different workspace
    is fine.
    """
    a = models.Workspace(key="A", name="A")
    b = models.Workspace(key="B", name="B")
    session.add_all([a, b])
    session.flush()

    session.add_all(
        [
            models.Tag(workspace_id=a.id, name="bug"),
            models.Tag(workspace_id=b.id, name="bug"),
        ]
    )
    session.commit()

    session.add(models.Tag(workspace_id=a.id, name="bug"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_linkage_endpoints_are_unique(session: Session) -> None:
    """
    The composite UNIQUE on (source_type, source_id, target_type,
    target_id, link_type) prevents the same edge from being recorded
    twice.
    """
    workspace = models.Workspace(key="KAN", name="K")
    session.add(workspace)
    session.flush()
    a = models.Story(workspace_id=workspace.id, human_id="KAN-1", title="A")
    b = models.Story(workspace_id=workspace.id, human_id="KAN-2", title="B")
    session.add_all([a, b])
    session.flush()

    session.add(
        models.Linkage(
            source_type="story",
            source_id=a.id,
            target_type="story",
            target_id=b.id,
            link_type="relates_to",
        )
    )
    session.commit()

    session.add(
        models.Linkage(
            source_type="story",
            source_id=a.id,
            target_type="story",
            target_id=b.id,
            link_type="relates_to",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_api_token_hash_is_unique(session: Session) -> None:
    """
    Two tokens cannot share the same SHA-256 hash.
    """
    session.add(
        models.ApiToken(
            token_hash="abc123",
            actor_type="human",
            actor_id="adam",
            name="laptop",
        )
    )
    session.commit()
    session.add(
        models.ApiToken(
            token_hash="abc123",
            actor_type="claude",
            actor_id="outer",
            name="mcp",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
