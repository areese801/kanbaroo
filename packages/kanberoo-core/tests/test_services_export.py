"""
Tests for :func:`kanberoo_core.services.export.export_workspace`.

These tests build a workspace with sample data, call the exporter,
and assert the archive contents line up with the data-portability
contract (spec section 2.4): Parquet per table, a self-contained
SQLite copy, and a schema-version manifest. The SQLite copy is
workspace-scoped and does not carry the ``api_tokens`` table.
"""

import io
import json
import sqlite3
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from sqlalchemy.orm import Session

from kanberoo_core import Actor, ActorType
from kanberoo_core.schemas.epic import EpicCreate
from kanberoo_core.schemas.story import StoryCreate
from kanberoo_core.schemas.workspace import WorkspaceCreate
from kanberoo_core.services import epics as epic_service
from kanberoo_core.services import stories as story_service
from kanberoo_core.services import workspaces as ws_service
from kanberoo_core.services.exceptions import NotFoundError
from kanberoo_core.services.export import (
    EXPORT_TABLE_NAMES,
    export_filename_for,
    export_workspace,
)

HUMAN = Actor(type=ActorType.HUMAN, id="adam")


def _seed_workspace(session: Session) -> tuple[str, str, list[str]]:
    """
    Create a workspace with an epic and two stories. Returns the
    workspace id, the epic id, and the story ids.
    """
    ws = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="KAN", name="Kanberoo"),
    )
    session.commit()
    epic = epic_service.create_epic(
        session,
        actor=HUMAN,
        workspace_id=ws.id,
        payload=EpicCreate(title="First milestone"),
    )
    session.commit()
    story_a = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=ws.id,
        payload=StoryCreate(title="In-epic", epic_id=epic.id),
    )
    story_b = story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=ws.id,
        payload=StoryCreate(title="No epic"),
    )
    session.commit()
    return ws.id, epic.id, [story_a.id, story_b.id]


def _extract_members(archive_bytes: bytes) -> dict[str, bytes]:
    """
    Read every member of a tar.gz archive into a name to bytes map.
    """
    members: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tf:
        for info in tf.getmembers():
            reader = tf.extractfile(info)
            assert reader is not None
            members[info.name] = reader.read()
    return members


def _read_parquet(data: bytes) -> list[dict[str, Any]]:
    """
    Round-trip a Parquet byte blob through pyarrow and return rows as
    a list of dicts. Uses pandas-free accessors so the test suite does
    not drag pandas in as a dev dep.
    """
    table = pq.read_table(io.BytesIO(data))
    rows: list[dict[str, Any]] = table.to_pylist()
    return rows


def test_export_archive_contains_expected_members(session: Session) -> None:
    """
    The archive always contains the manifest, a Parquet file per
    table, and the SQLite copy.
    """
    workspace_id, _epic_id, _story_ids = _seed_workspace(session)
    archive = export_workspace(session, workspace_id=workspace_id)
    members = _extract_members(archive)

    expected_members = {"schema_version.json", "kanberoo.db"} | {
        f"tables/{name}.parquet" for name in EXPORT_TABLE_NAMES
    }
    assert set(members) == expected_members


def test_export_manifest_has_revision_and_workspace(session: Session) -> None:
    """
    ``schema_version.json`` carries the Alembic revision and the target
    workspace's identity so external readers can pick the right
    loader.
    """
    workspace_id, _epic_id, _story_ids = _seed_workspace(session)
    archive = export_workspace(session, workspace_id=workspace_id)
    members = _extract_members(archive)

    manifest = json.loads(members["schema_version.json"].decode("utf-8"))
    assert manifest["alembic_revision"] == "0001_initial"
    assert manifest["workspace_id"] == workspace_id
    assert manifest["workspace_key"] == "KAN"
    assert manifest["created_at"].endswith("Z")


def test_export_parquet_rows_round_trip(session: Session) -> None:
    """
    Parquet files round-trip through pyarrow and contain exactly the
    workspace's live rows.
    """
    workspace_id, epic_id, story_ids = _seed_workspace(session)
    archive = export_workspace(session, workspace_id=workspace_id)
    members = _extract_members(archive)

    workspace_rows = _read_parquet(members["tables/workspaces.parquet"])
    assert [row["id"] for row in workspace_rows] == [workspace_id]
    assert workspace_rows[0]["key"] == "KAN"
    # next_issue_num bumps every issue allocation; one epic + two stories.
    assert workspace_rows[0]["next_issue_num"] == 4

    epic_rows = _read_parquet(members["tables/epics.parquet"])
    assert [row["id"] for row in epic_rows] == [epic_id]

    story_rows = _read_parquet(members["tables/stories.parquet"])
    assert sorted(row["id"] for row in story_rows) == sorted(story_ids)

    audit_rows = _read_parquet(members["tables/audit_events.parquet"])
    audit_entity_ids = {row["entity_id"] for row in audit_rows}
    assert workspace_id in audit_entity_ids
    assert epic_id in audit_entity_ids
    for story_id in story_ids:
        assert story_id in audit_entity_ids


def test_export_sqlite_copy_has_only_workspace_rows(session: Session) -> None:
    """
    The embedded ``kanberoo.db`` carries the full schema (minus
    ``api_tokens``) and exactly the workspace's rows.
    """
    workspace_id, _epic_id, story_ids = _seed_workspace(session)
    # Seed a second workspace so the exporter has to filter.
    other = ws_service.create_workspace(
        session,
        actor=HUMAN,
        payload=WorkspaceCreate(key="ENG", name="Engineering"),
    )
    session.commit()
    story_service.create_story(
        session,
        actor=HUMAN,
        workspace_id=other.id,
        payload=StoryCreate(title="Different workspace"),
    )
    session.commit()

    archive = export_workspace(session, workspace_id=workspace_id)
    members = _extract_members(archive)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "kanberoo.db"
        db_path.write_bytes(members["kanberoo.db"])
        conn = sqlite3.connect(db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "api_tokens" not in tables
            assert "workspaces" in tables

            workspace_keys = [
                row[0] for row in conn.execute("SELECT key FROM workspaces").fetchall()
            ]
            assert workspace_keys == ["KAN"]

            copied_story_ids = {
                row[0] for row in conn.execute("SELECT id FROM stories").fetchall()
            }
            assert copied_story_ids == set(story_ids)
        finally:
            conn.close()


def test_export_hides_soft_deleted_rows_by_default(session: Session) -> None:
    """
    Soft-deleted stories are excluded from both the Parquet set and
    the SQLite copy when ``include_deleted`` is False.
    """
    workspace_id, _epic_id, story_ids = _seed_workspace(session)
    deleted_story = story_service.get_story(session, story_id=story_ids[0])
    story_service.soft_delete_story(
        session,
        actor=HUMAN,
        story_id=deleted_story.id,
        expected_version=deleted_story.version,
    )
    session.commit()

    archive = export_workspace(session, workspace_id=workspace_id)
    members = _extract_members(archive)
    live_story_ids = {
        row["id"] for row in _read_parquet(members["tables/stories.parquet"])
    }
    assert deleted_story.id not in live_story_ids

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "kanberoo.db"
        db_path.write_bytes(members["kanberoo.db"])
        conn = sqlite3.connect(db_path)
        try:
            copied_story_ids = {
                row[0] for row in conn.execute("SELECT id FROM stories").fetchall()
            }
            assert deleted_story.id not in copied_story_ids
        finally:
            conn.close()


def test_export_includes_deleted_when_asked(session: Session) -> None:
    """
    ``include_deleted=True`` carries soft-deleted rows through to both
    outputs so admin snapshots are round-trip-complete.
    """
    workspace_id, _epic_id, story_ids = _seed_workspace(session)
    deleted_story = story_service.get_story(session, story_id=story_ids[0])
    story_service.soft_delete_story(
        session,
        actor=HUMAN,
        story_id=deleted_story.id,
        expected_version=deleted_story.version,
    )
    session.commit()

    archive = export_workspace(
        session,
        workspace_id=workspace_id,
        include_deleted=True,
    )
    members = _extract_members(archive)
    parquet_story_ids = {
        row["id"] for row in _read_parquet(members["tables/stories.parquet"])
    }
    assert deleted_story.id in parquet_story_ids

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "kanberoo.db"
        db_path.write_bytes(members["kanberoo.db"])
        conn = sqlite3.connect(db_path)
        try:
            copied_story_ids = {
                row[0] for row in conn.execute("SELECT id FROM stories").fetchall()
            }
            assert deleted_story.id in copied_story_ids
        finally:
            conn.close()


def test_export_unknown_workspace_raises(session: Session) -> None:
    """
    The exporter propagates ``NotFoundError`` for an unknown id so the
    API layer renders a clean 404.
    """
    try:
        export_workspace(session, workspace_id="does-not-exist")
    except NotFoundError:
        return
    raise AssertionError("expected NotFoundError")


def test_export_filename_contains_key_and_timestamp() -> None:
    """
    ``export_filename_for`` returns a stable filename suitable for
    Content-Disposition.
    """
    name = export_filename_for("KAN", now="2026-04-18T12:34:56.000000Z")
    assert name.startswith("KAN-export-")
    assert name.endswith(".tar.gz")
    assert ":" not in name
