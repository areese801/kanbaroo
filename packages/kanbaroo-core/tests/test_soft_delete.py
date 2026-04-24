"""
Soft delete is the only supported delete operation in Kanbaroo.

The :func:`live` query helper filters out rows whose ``deleted_at`` is
non-null. This test verifies the contract: setting ``deleted_at`` on a
row hides it from ``live`` queries while a plain ``select`` continues
to return it.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from kanbaroo_core import live, models, utc_now_iso


def test_live_helper_excludes_soft_deleted_rows(session: Session) -> None:
    """
    A soft-deleted story is invisible to ``live(select(Story), Story)``
    but still present when the filter is omitted.
    """
    workspace = models.Workspace(key="KAN", name="Kanbaroo")
    session.add(workspace)
    session.flush()

    keeper = models.Story(workspace_id=workspace.id, human_id="KAN-1", title="Keeper")
    goner = models.Story(workspace_id=workspace.id, human_id="KAN-2", title="Goner")
    session.add_all([keeper, goner])
    session.commit()

    goner.deleted_at = utc_now_iso()
    session.commit()

    all_rows = session.execute(select(models.Story)).scalars().all()
    live_rows = (
        session.execute(live(select(models.Story), models.Story)).scalars().all()
    )

    assert {s.id for s in all_rows} == {keeper.id, goner.id}
    assert {s.id for s in live_rows} == {keeper.id}


def test_live_helper_filters_multiple_models(session: Session) -> None:
    """
    ``live`` is variadic so a join across two soft-deletable tables can
    be filtered in a single call.
    """
    workspace = models.Workspace(key="KAN", name="Kanbaroo")
    session.add(workspace)
    session.flush()
    epic = models.Epic(workspace_id=workspace.id, human_id="KAN-1", title="E")
    session.add(epic)
    session.flush()
    story = models.Story(
        workspace_id=workspace.id,
        epic_id=epic.id,
        human_id="KAN-2",
        title="S",
    )
    session.add(story)
    session.commit()

    epic.deleted_at = utc_now_iso()
    session.commit()

    stmt = live(
        select(models.Story).join(models.Epic, models.Story.epic_id == models.Epic.id),
        models.Story,
        models.Epic,
    )
    rows = session.execute(stmt).scalars().all()
    assert rows == []
