"""
Service-layer tests for the duplicate-detection helpers
(``find_similar_stories`` / ``find_similar_epics`` / ``find_similar_tags``).

The helpers do no I/O beyond the workspace they're scoped to, so the
focus is on the normalization rules and workspace isolation: a tag
named ``bug`` in workspace A must not match a tag of the same name
in workspace B.
"""

from sqlalchemy.orm import Session

from kanbaroo_core import Actor, ActorType
from kanbaroo_core.schemas.epic import EpicCreate
from kanbaroo_core.schemas.story import StoryCreate
from kanbaroo_core.schemas.tag import TagCreate
from kanbaroo_core.schemas.workspace import WorkspaceCreate
from kanbaroo_core.services import epics as epic_service
from kanbaroo_core.services import stories as story_service
from kanbaroo_core.services import tags as tag_service
from kanbaroo_core.services import workspaces as ws_service

HUMAN = Actor(type=ActorType.HUMAN, id="adam")


def _make_workspace(session: Session, *, key: str = "KAN") -> str:
    """
    Create a workspace and return its id.
    """
    ws = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key=key, name=f"{key} workspace"),
    )
    session.commit()
    return ws.id


def test_find_similar_stories_exact_match(session: Session) -> None:
    """
    A story whose title matches verbatim is returned.
    """
    ws_id = _make_workspace(session)
    story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=ws_id,
        payload=StoryCreate(title="Fix the bug"),
    )
    session.commit()
    matches = story_service.find_similar_stories(
        session, workspace_id=ws_id, title="Fix the bug"
    )
    assert [s.title for s in matches] == ["Fix the bug"]


def test_find_similar_stories_case_insensitive(session: Session) -> None:
    """
    Casing differences should not prevent a match.
    """
    ws_id = _make_workspace(session)
    story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=ws_id,
        payload=StoryCreate(title="Fix the bug"),
    )
    session.commit()
    matches = story_service.find_similar_stories(
        session, workspace_id=ws_id, title="FIX THE BUG"
    )
    assert len(matches) == 1


def test_find_similar_stories_punctuation_insensitive(session: Session) -> None:
    """
    Different punctuation collapses to the same comparison key.
    """
    ws_id = _make_workspace(session)
    story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=ws_id,
        payload=StoryCreate(title="fix-the-bug"),
    )
    session.commit()
    matches = story_service.find_similar_stories(
        session, workspace_id=ws_id, title="Fix the bug!"
    )
    assert len(matches) == 1


def test_find_similar_stories_no_match(session: Session) -> None:
    """
    Distinct word content yields an empty list.
    """
    ws_id = _make_workspace(session)
    story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=ws_id,
        payload=StoryCreate(title="Fix the bug"),
    )
    session.commit()
    matches = story_service.find_similar_stories(
        session, workspace_id=ws_id, title="Wholly different work"
    )
    assert matches == []


def test_find_similar_stories_isolated_per_workspace(session: Session) -> None:
    """
    Stories in another workspace are invisible.
    """
    ws_a = _make_workspace(session, key="KAN")
    ws_b = _make_workspace(session, key="OPS")
    story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=ws_b,
        payload=StoryCreate(title="Fix the bug"),
    )
    session.commit()
    matches = story_service.find_similar_stories(
        session, workspace_id=ws_a, title="Fix the bug"
    )
    assert matches == []


def test_find_similar_stories_skips_soft_deleted_by_default(
    session: Session,
) -> None:
    """
    Soft-deleted stories are excluded unless ``include_deleted=True``.
    """
    ws_id = _make_workspace(session)
    story = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=ws_id,
        payload=StoryCreate(title="Fix the bug"),
    )
    session.commit()
    story_service.soft_delete_story(
        session, actor=HUMAN, story_id=story.id, expected_version=story.version
    )
    session.commit()
    assert (
        story_service.find_similar_stories(
            session, workspace_id=ws_id, title="Fix the bug"
        )
        == []
    )
    matches = story_service.find_similar_stories(
        session,
        workspace_id=ws_id,
        title="Fix the bug",
        include_deleted=True,
    )
    assert len(matches) == 1


def test_find_similar_stories_empty_normalization(session: Session) -> None:
    """
    A title that normalizes to the empty string returns no matches
    so callers do not flood the user with everything in the
    workspace.
    """
    ws_id = _make_workspace(session)
    story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=ws_id,
        payload=StoryCreate(title="Fix the bug"),
    )
    session.commit()
    assert (
        story_service.find_similar_stories(session, workspace_id=ws_id, title="!!!")
        == []
    )


def test_find_similar_epics_exact_and_punctuation(session: Session) -> None:
    """
    Epic helper mirrors the story helper for casing and punctuation.
    """
    ws_id = _make_workspace(session)
    epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=ws_id,
        payload=EpicCreate(title="v2 Redesign"),
    )
    session.commit()
    matches = epic_service.find_similar_epics(
        session, workspace_id=ws_id, title="v2-redesign"
    )
    assert len(matches) == 1


def test_find_similar_epics_isolated_per_workspace(session: Session) -> None:
    """
    Epics in another workspace are invisible.
    """
    ws_a = _make_workspace(session, key="KAN")
    ws_b = _make_workspace(session, key="OPS")
    epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=ws_b,
        payload=EpicCreate(title="v2 Redesign"),
    )
    session.commit()
    matches = epic_service.find_similar_epics(
        session, workspace_id=ws_a, title="v2 redesign"
    )
    assert matches == []


def test_find_similar_tags_exact_and_punctuation(session: Session) -> None:
    """
    Tag helper catches the case the unique constraint cannot:
    visually similar names with different casing or punctuation.
    """
    ws_id = _make_workspace(session)
    tag_service.create_tag(
        session,
        actor=HUMAN,
        workspace_id=ws_id,
        payload=TagCreate(name="UI"),
    )
    session.commit()
    matches = tag_service.find_similar_tags(session, workspace_id=ws_id, name="u-i")
    assert len(matches) == 1


def test_find_similar_tags_isolated_per_workspace(session: Session) -> None:
    """
    Tags in another workspace are invisible.
    """
    ws_a = _make_workspace(session, key="KAN")
    ws_b = _make_workspace(session, key="OPS")
    tag_service.create_tag(
        session,
        actor=HUMAN,
        workspace_id=ws_b,
        payload=TagCreate(name="bug"),
    )
    session.commit()
    matches = tag_service.find_similar_tags(session, workspace_id=ws_a, name="bug")
    assert matches == []
