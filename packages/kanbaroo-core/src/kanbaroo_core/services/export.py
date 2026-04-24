"""
Workspace export service (spec section 2.4).

Builds a ``tar.gz`` archive containing:

* ``schema_version.json`` -Alembic head revision plus workspace
  identity and the export timestamp.
* ``tables/*.parquet`` -one Parquet file per table, containing only
  the rows belonging to the target workspace.
* ``kanbaroo.db`` -a fresh SQLite file with the same schema and the
  workspace-scoped rows copied in. Self-contained for restore or
  side-by-side analysis.

``api_tokens`` are intentionally excluded from both the Parquet set
and the SQLite copy: tokens leak auth material even as SHA-256 hashes.
Linkages are included whenever either endpoint touches a workspace
story or epic (cross-workspace linkages are allowed per spec §10 Q2,
so both halves show up in both exports).

Audit events have no ``deleted_at`` column, so they are always
included; they are a historical fact rather than a mutable entity.
"""

from __future__ import annotations

import io
import json
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from alembic.script import ScriptDirectory
from sqlalchemy import Integer, Table, or_, select
from sqlalchemy.orm import Session

from kanbaroo_core.db import Base, engine_for_url
from kanbaroo_core.migrations import build_alembic_config
from kanbaroo_core.models.audit import AuditEvent
from kanbaroo_core.models.comment import Comment
from kanbaroo_core.models.epic import Epic
from kanbaroo_core.models.linkage import Linkage
from kanbaroo_core.models.story import Story
from kanbaroo_core.models.story_tag import story_tags
from kanbaroo_core.models.tag import Tag
from kanbaroo_core.models.workspace import Workspace, WorkspaceRepo
from kanbaroo_core.services.workspaces import get_workspace
from kanbaroo_core.time import utc_now_iso

EXPORT_TABLE_NAMES: tuple[str, ...] = (
    "workspaces",
    "workspace_repos",
    "epics",
    "stories",
    "linkages",
    "comments",
    "tags",
    "story_tags",
    "audit_events",
)

_LIVE_FILTERABLE: frozenset[str] = frozenset(
    {"workspaces", "epics", "stories", "linkages", "comments", "tags"}
)


def _alembic_head() -> str:
    """
    Return the current Alembic head revision.

    The export manifest records this so external readers can tell which
    schema version the archive was produced against without inspecting
    the SQLite file.
    """
    cfg = build_alembic_config("sqlite:///:memory:")
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    return heads[0] if heads else ""


def _arrow_schema_for_table(table: Table) -> pa.Schema:
    """
    Build a :class:`pyarrow.Schema` that mirrors the SQLAlchemy table.

    Every Integer column becomes ``int64``; every other column becomes
    a nullable ``string``. This is enough to keep empty Parquet files
    self-describing and to round-trip the TEXT/INTEGER storage Kanbaroo
    uses end to end.
    """
    fields: list[pa.Field] = []
    for col in table.columns:
        arrow_type: pa.DataType = (
            pa.int64() if isinstance(col.type, Integer) else pa.string()
        )
        fields.append(pa.field(col.name, arrow_type, nullable=bool(col.nullable)))
    return pa.schema(fields)


def _fetch_table_rows(
    session: Session,
    table: Table,
    *,
    where_clauses: list[Any],
    include_deleted: bool,
) -> list[dict[str, Any]]:
    """
    SELECT a table's rows as a list of column-name dictionaries.

    Applies ``deleted_at IS NULL`` when the table has that column and
    ``include_deleted`` is False. The dict shape matches what
    ``Connection.execute(table.insert(), rows)`` expects, so the same
    list feeds both the Parquet writer and the SQLite copy.
    """
    stmt = select(table)
    for clause in where_clauses:
        stmt = stmt.where(clause)
    if not include_deleted and "deleted_at" in table.c:
        stmt = stmt.where(table.c.deleted_at.is_(None))
    rows = session.execute(stmt).all()
    return [dict(row._mapping) for row in rows]


def _add_bytes(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    """
    Append a single byte blob as ``name`` inside ``archive``.
    """
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))


def _write_parquet(table: Table, rows: list[dict[str, Any]]) -> bytes:
    """
    Serialise ``rows`` to Parquet bytes using ``table``'s derived schema.

    An explicit schema means empty tables still round-trip with the
    correct column names and types, so external readers (DuckDB,
    Snowflake) can open the file without special-casing.
    """
    schema = _arrow_schema_for_table(table)
    arrow_table = pa.Table.from_pylist(list(rows), schema=schema)
    buffer = io.BytesIO()
    pq.write_table(arrow_table, buffer)
    return buffer.getvalue()


def _build_sqlite_copy(
    rows_by_table: dict[str, list[dict[str, Any]]],
    table_objects: dict[str, Table],
) -> bytes:
    """
    Build a fresh SQLite database file containing only the supplied rows.

    The database is created with the full Kanbaroo schema (via
    ``Base.metadata.create_all``) and the ``api_tokens`` table is then
    dropped so credential material never ships with an export. Rows are
    inserted in FK-safe order (workspaces first, association tables
    last) so the foreign-key pragma stays happy.
    """
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "kanbaroo.db"
        engine = engine_for_url(f"sqlite:///{db_path}")
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as conn:
                conn.exec_driver_sql("DROP TABLE IF EXISTS api_tokens")
                for name in EXPORT_TABLE_NAMES:
                    rows = rows_by_table[name]
                    if not rows:
                        continue
                    conn.execute(table_objects[name].insert(), rows)
        finally:
            engine.dispose()
        return db_path.read_bytes()


def export_workspace(
    session: Session,
    *,
    workspace_id: str,
    include_deleted: bool = False,
) -> bytes:
    """
    Build and return a ``tar.gz`` export archive for ``workspace_id``.

    Raises :class:`~kanbaroo_core.services.exceptions.NotFoundError`
    when the workspace does not exist or is soft-deleted and
    ``include_deleted`` is False. Returns the archive as raw bytes so
    the API layer can stream it back without touching disk.
    """
    workspace = get_workspace(
        session,
        workspace_id=workspace_id,
        include_deleted=include_deleted,
    )

    table_objects: dict[str, Table] = {
        "workspaces": Workspace.__table__,  # type: ignore[dict-item]
        "workspace_repos": WorkspaceRepo.__table__,  # type: ignore[dict-item]
        "epics": Epic.__table__,  # type: ignore[dict-item]
        "stories": Story.__table__,  # type: ignore[dict-item]
        "linkages": Linkage.__table__,  # type: ignore[dict-item]
        "comments": Comment.__table__,  # type: ignore[dict-item]
        "tags": Tag.__table__,  # type: ignore[dict-item]
        "story_tags": story_tags,
        "audit_events": AuditEvent.__table__,  # type: ignore[dict-item]
    }

    workspaces_tbl = table_objects["workspaces"]
    workspace_rows = _fetch_table_rows(
        session,
        workspaces_tbl,
        where_clauses=[workspaces_tbl.c.id == workspace.id],
        include_deleted=True,
    )

    repos_tbl = table_objects["workspace_repos"]
    repo_rows = _fetch_table_rows(
        session,
        repos_tbl,
        where_clauses=[repos_tbl.c.workspace_id == workspace.id],
        include_deleted=include_deleted,
    )

    epics_tbl = table_objects["epics"]
    epic_rows = _fetch_table_rows(
        session,
        epics_tbl,
        where_clauses=[epics_tbl.c.workspace_id == workspace.id],
        include_deleted=include_deleted,
    )
    epic_ids = [r["id"] for r in epic_rows]

    stories_tbl = table_objects["stories"]
    story_rows = _fetch_table_rows(
        session,
        stories_tbl,
        where_clauses=[stories_tbl.c.workspace_id == workspace.id],
        include_deleted=include_deleted,
    )
    story_ids = [r["id"] for r in story_rows]

    linkages_tbl = table_objects["linkages"]
    endpoint_ids = story_ids + epic_ids
    linkage_rows: list[dict[str, Any]]
    if endpoint_ids:
        linkage_rows = _fetch_table_rows(
            session,
            linkages_tbl,
            where_clauses=[
                or_(
                    linkages_tbl.c.source_id.in_(endpoint_ids),
                    linkages_tbl.c.target_id.in_(endpoint_ids),
                )
            ],
            include_deleted=include_deleted,
        )
    else:
        linkage_rows = []

    comments_tbl = table_objects["comments"]
    comment_rows: list[dict[str, Any]]
    if story_ids:
        comment_rows = _fetch_table_rows(
            session,
            comments_tbl,
            where_clauses=[comments_tbl.c.story_id.in_(story_ids)],
            include_deleted=include_deleted,
        )
    else:
        comment_rows = []

    tags_tbl = table_objects["tags"]
    tag_rows = _fetch_table_rows(
        session,
        tags_tbl,
        where_clauses=[tags_tbl.c.workspace_id == workspace.id],
        include_deleted=include_deleted,
    )
    tag_ids = [r["id"] for r in tag_rows]

    story_tag_rows: list[dict[str, Any]]
    if story_ids and tag_ids:
        story_tag_rows = _fetch_table_rows(
            session,
            story_tags,
            where_clauses=[
                story_tags.c.story_id.in_(story_ids),
                story_tags.c.tag_id.in_(tag_ids),
            ],
            include_deleted=True,
        )
    else:
        story_tag_rows = []

    audit_tbl = table_objects["audit_events"]
    relevant_entity_ids: set[str] = (
        {workspace.id}
        | set(epic_ids)
        | set(story_ids)
        | set(tag_ids)
        | {r["id"] for r in comment_rows}
        | {r["id"] for r in linkage_rows}
    )
    audit_rows: list[dict[str, Any]]
    if relevant_entity_ids:
        audit_rows = _fetch_table_rows(
            session,
            audit_tbl,
            where_clauses=[audit_tbl.c.entity_id.in_(relevant_entity_ids)],
            include_deleted=True,
        )
    else:
        audit_rows = []

    rows_by_table: dict[str, list[dict[str, Any]]] = {
        "workspaces": workspace_rows,
        "workspace_repos": repo_rows,
        "epics": epic_rows,
        "stories": story_rows,
        "linkages": linkage_rows,
        "comments": comment_rows,
        "tags": tag_rows,
        "story_tags": story_tag_rows,
        "audit_events": audit_rows,
    }

    manifest: dict[str, Any] = {
        "alembic_revision": _alembic_head(),
        "created_at": utc_now_iso(),
        "workspace_id": workspace.id,
        "workspace_key": workspace.key,
    }
    if include_deleted:
        manifest["include_deleted"] = True

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        _add_bytes(
            archive,
            "schema_version.json",
            json.dumps(manifest, sort_keys=True).encode("utf-8"),
        )
        for name in EXPORT_TABLE_NAMES:
            parquet_bytes = _write_parquet(table_objects[name], rows_by_table[name])
            _add_bytes(archive, f"tables/{name}.parquet", parquet_bytes)
        _add_bytes(
            archive,
            "kanbaroo.db",
            _build_sqlite_copy(rows_by_table, table_objects),
        )

    return buffer.getvalue()


def export_filename_for(workspace_key: str, *, now: str | None = None) -> str:
    """
    Build the default filename for an export archive.

    ``now`` defaults to the current UTC timestamp; the API layer passes
    it in so Content-Disposition and the manifest agree.
    """
    iso = now or utc_now_iso()
    # Swap ``:`` so the filename survives Windows and HTTP parameter
    # quirks without needing extra quoting.
    safe_time = iso.replace(":", "").replace(".", "")
    return f"{workspace_key}-export-{safe_time}.tar.gz"


__all__ = [
    "EXPORT_TABLE_NAMES",
    "export_filename_for",
    "export_workspace",
]
