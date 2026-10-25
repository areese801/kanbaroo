"""
Timestamp invariants.

Per ``docs/spec.md`` section 3.4, every timestamp column stores ISO 8601
TEXT in UTC with a ``Z`` suffix, e.g. ``2026-04-17T15:30:00Z``. External
direct readers (DuckDB, Snowflake, GitHub Actions) rely on this format.
"""

import re
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from kanbaroo_core import models, utc_now_iso
from kanbaroo_core.time import format_utc_iso, parse_utc_iso

_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_utc_now_iso_format() -> None:
    """
    The shared ``utc_now_iso`` helper produces a string in the canonical
    Kanbaroo format and parses round-trip as UTC.
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
    workspace = models.Workspace(key="KAN", name="Kanbaroo")
    session.add(workspace)
    session.commit()

    assert _ISO_UTC.match(workspace.created_at), workspace.created_at
    assert _ISO_UTC.match(workspace.updated_at), workspace.updated_at


def test_parse_utc_iso_round_trips_canonical_format() -> None:
    """
    The canonical ``Z``-suffixed string parses to an aware UTC datetime
    and formats back to the identical string.
    """
    parsed = parse_utc_iso("2026-10-25T12:00:00Z")
    assert parsed == datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)
    assert format_utc_iso(parsed) == "2026-10-25T12:00:00Z"


def test_parse_utc_iso_accepts_offsets_and_naive_values() -> None:
    """
    Explicit offsets are normalized to UTC; naive values are assumed UTC.
    """
    assert parse_utc_iso("2026-10-25T14:00:00+02:00") == datetime(
        2026, 10, 25, 12, 0, 0, tzinfo=UTC
    )
    assert parse_utc_iso("2026-10-25T12:00:00") == datetime(
        2026, 10, 25, 12, 0, 0, tzinfo=UTC
    )


def test_parse_utc_iso_returns_none_for_bad_input() -> None:
    """
    ``None``, empty, and unparseable values yield ``None`` rather than
    raising, so callers can treat them as "unknown".
    """
    assert parse_utc_iso(None) is None
    assert parse_utc_iso("") is None
    assert parse_utc_iso("not a timestamp") is None
