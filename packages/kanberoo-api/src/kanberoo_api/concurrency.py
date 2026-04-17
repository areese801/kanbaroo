"""
Helpers for ETag and If-Match handling.

Every mutable entity in Kanberoo exposes its ``version`` via the ETag
response header and requires clients to send ``If-Match: <version>``
on updates. These helpers centralise the parsing and formatting so
routers stay thin and the exact wire format is easy to audit.
"""

from fastapi import HTTPException, Request, status


def etag_for(version: int) -> str:
    """
    Format a ``version`` integer as an ETag header value.

    The format is deliberately minimal: just the stringified integer,
    no quotes or ``W/`` prefix. ``docs/spec.md`` section 4.1 defines
    the ETag as the current version; that's the exact contract we
    emit.
    """
    return str(version)


def etag_headers(version: int) -> dict[str, str]:
    """
    Return the ``{"ETag": ...}`` header dict for a response.
    """
    return {"ETag": etag_for(version)}


def parse_if_match(request: Request) -> int:
    """
    Extract and int-parse the ``If-Match`` header.

    Missing and malformed values both raise 400 with the canonical
    error envelope. The spec requires ``If-Match`` on every mutating
    endpoint; there is no "weak match" or wildcard support.
    """
    raw = request.headers.get("if-match")
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "missing_if_match",
                "message": "If-Match header is required for mutations",
                "details": None,
            },
        )
    try:
        return int(raw.strip().strip('"'))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "malformed_if_match",
                "message": "If-Match header must be an integer version",
                "details": {"received": raw},
            },
        ) from exc
