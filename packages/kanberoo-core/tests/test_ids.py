"""
Primary keys must be UUID v7.

UUID v7 is required because Kanberoo relies on insert-locality and
chronological sortability of audit events (see ``docs/spec.md`` section
3.4). The stdlib ``uuid.uuid4()`` would silently break both invariants.
"""

import uuid

from sqlalchemy.orm import Session

from kanberoo_core import models
from kanberoo_core.db import new_id


def _is_uuid_v7(value: str) -> bool:
    """
    Return True if ``value`` parses as a UUID and has version 7.
    """
    parsed = uuid.UUID(value)
    return parsed.version == 7


def test_new_id_returns_uuid_v7() -> None:
    """
    The shared ID factory hands out UUID v7 strings.
    """
    fresh = new_id()
    assert _is_uuid_v7(fresh)


def test_workspace_default_id_is_uuid_v7(session: Session) -> None:
    """
    A workspace created without an explicit id receives a UUID v7.
    """
    workspace = models.Workspace(key="KAN", name="Kanberoo")
    session.add(workspace)
    session.flush()
    assert _is_uuid_v7(workspace.id)


def test_story_and_other_entities_use_uuid_v7(session: Session) -> None:
    """
    Every entity with a UUID primary key uses v7 by default.
    """
    workspace = models.Workspace(key="KAN", name="Kanberoo")
    session.add(workspace)
    session.flush()

    epic = models.Epic(workspace_id=workspace.id, human_id="KAN-1", title="Epic")
    story = models.Story(workspace_id=workspace.id, human_id="KAN-2", title="Story")
    tag = models.Tag(workspace_id=workspace.id, name="bug")
    repo = models.WorkspaceRepo(
        workspace_id=workspace.id,
        label="backend",
        repo_url="https://example.com/repo.git",
    )
    session.add_all([epic, story, tag, repo])
    session.flush()
    comment = models.Comment(
        story_id=story.id, body="hi", actor_type="human", actor_id="adam"
    )
    session.add(comment)
    session.flush()

    for entity in (workspace, epic, story, tag, repo, comment):
        assert _is_uuid_v7(entity.id), f"{type(entity).__name__} id not v7"
