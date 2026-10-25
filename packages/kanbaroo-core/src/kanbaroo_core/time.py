"""
Timestamp utilities.

All timestamps in Kanbaroo are stored as ISO 8601 TEXT in UTC with a ``Z``
suffix (e.g. ``2026-04-17T15:30:00Z``). This convention is documented in
``docs/spec.md`` section 3.4 and is the contract that direct database
readers (DuckDB, Snowflake, GitHub Actions) rely on.
"""

from datetime import UTC, datetime

ISO_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def format_utc_iso(value: datetime) -> str:
    """
    Format an aware (or naive, assumed-UTC) datetime as the canonical
    ISO 8601 UTC string with seconds resolution and a trailing ``Z``.
    """
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.strftime(ISO_UTC_FORMAT)


def utc_now_iso() -> str:
    """
    Return the current UTC time as an ISO 8601 string.

    Uses seconds resolution and a trailing ``Z`` for the UTC offset. Suitable
    as a SQLAlchemy column ``default``/``onupdate`` callable.
    """
    return format_utc_iso(datetime.now(UTC))


def parse_utc_iso(value: str | None) -> datetime | None:
    """
    Parse a stored ISO 8601 timestamp into an aware UTC datetime.

    Accepts the canonical ``Z`` suffix as well as explicit offsets and
    naive values (treated as UTC). Returns ``None`` for ``None``, empty,
    or unparseable input so callers reading possibly hand-edited rows
    can treat a bad value as "unknown" instead of raising.
    """
    if not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
