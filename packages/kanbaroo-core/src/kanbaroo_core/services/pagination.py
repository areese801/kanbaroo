"""
Cursor pagination helpers shared by the list services.

Every paginated list endpoint in Kanbaroo uses the same scheme (see
``docs/spec.md`` section 4.1): rows are ordered by primary key, the
page size is clamped to ``[1, MAX_PAGE_LIMIT]``, and ``next_cursor``
is the last row's id wrapped in URL-safe base64. The cursor is opaque
to clients; the encoding is purely a signal that it should not be
interpreted.

Services that paginate over a different entity (stories, comments)
share these helpers so the wire format cannot drift between them.
"""

import base64

from kanbaroo_core.services.exceptions import ValidationError

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200


def clamp_limit(limit: int) -> int:
    """
    Clamp a requested page size to the inclusive range
    ``[1, MAX_PAGE_LIMIT]``.
    """
    if limit < 1:
        return 1
    if limit > MAX_PAGE_LIMIT:
        return MAX_PAGE_LIMIT
    return limit


def encode_cursor(entity_id: str) -> str:
    """
    Encode an entity id as an opaque URL-safe cursor.
    """
    return base64.urlsafe_b64encode(entity_id.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> str:
    """
    Decode a cursor back into the entity id it wraps.

    Raises :class:`ValidationError` if the cursor is not valid base64
    URL-safe data; this translates to a 400 at the API layer.
    """
    try:
        return base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("cursor", "malformed cursor value") from exc
