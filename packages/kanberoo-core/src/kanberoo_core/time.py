"""
Timestamp utilities.

All timestamps in Kanberoo are stored as ISO 8601 TEXT in UTC with a ``Z``
suffix (e.g. ``2026-04-17T15:30:00Z``). This convention is documented in
``docs/spec.md`` section 3.4 and is the contract that direct database
readers (DuckDB, Snowflake, GitHub Actions) rely on.
"""

from datetime import UTC, datetime


def utc_now_iso() -> str:
    """
    Return the current UTC time as an ISO 8601 string.

    Uses seconds resolution and a trailing ``Z`` for the UTC offset. Suitable
    as a SQLAlchemy column ``default``/``onupdate`` callable.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
