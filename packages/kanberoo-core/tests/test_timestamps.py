"""
Timestamp invariants.

Per ``docs/spec.md`` section 3.4, every timestamp column stores ISO 8601
TEXT in UTC with a ``Z`` suffix, e.g. ``2026-04-17T15:30:00Z``. External
direct readers (DuckDB, Snowflake, GitHub Actions) rely on this format.
"""

import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from kanberoo_core import models, utc_now_iso

_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_utc_now_iso_format() -> None:
    """
    The shared ``utc_now_iso`` helper produces a string in the canonical
    Kanberoo format and parses round-trip as UTC.
    """
    value = utc_now_iso()
    assert _ISO_UTC.match(value), value
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert parsed.tzinfo == UTC


def test_workspace_timestamps_are_iso_utc(session: Session) -> None:
    """
    A newly persisted workspace has ``created_at`` and ``updated_at`` in
    the canonical format.
    """
    workspace = models.Workspace(key="KAN", name="Kanberoo")
    session.add(workspace)
    session.commit()

    assert _ISO_UTC.match(workspace.created_at), workspace.created_at
    assert _ISO_UTC.match(workspace.updated_at), workspace.updated_at
