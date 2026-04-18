"""
Implementation of ``kb audit``.

Calls the ``/audit/entity/{entity_type}/{id}`` endpoint per spec
section 4.2. That endpoint is not yet implemented on the server as of
this cage (the GET-audit router belongs to a later cage); when the
server returns 404 the CLI prints a clear message rather than a
traceback, so the contract is stable for callers even while the
backend catches up.

``kb audit`` accepts a human id (``KAN-123``) or a UUID. For human
ids we try ``/stories/by-key`` first and fall back to
``/epics/by-key``; that lets the same command serve either kind of
entity without the user having to specify the type.
"""

from __future__ import annotations

from typing import Any

import typer

from kanberoo_cli.client import ApiClient, ApiError, ApiRequestError
from kanberoo_cli.context import build_client, require_config
from kanberoo_cli.rendering import (
    exit_on_api_error,
    print_json,
    print_table,
)


def _resolve_entity(client: ApiClient, ref: str) -> tuple[str, str, str]:
    """
    Resolve ``ref`` to a ``(entity_type, entity_id, human_id_or_ref)``
    triple.

    For a human id (``KAN-N``) this hits ``by-key`` on both stories
    and epics; for a UUID it tries story-by-id then epic-by-id.
    Raises :class:`ApiRequestError` with ``not_found`` when neither
    lookup succeeds, so the CLI's error path is uniform.
    """
    if "-" in ref and ref.rsplit("-", 1)[-1].isdigit():
        try:
            body = client.get(f"/stories/by-key/{ref}").json()
            return "story", str(body["id"]), str(body["human_id"])
        except ApiRequestError as exc:
            if exc.code != "not_found":
                raise
        try:
            body = client.get(f"/epics/by-key/{ref}").json()
            return "epic", str(body["id"]), str(body["human_id"])
        except ApiRequestError as exc:
            if exc.code != "not_found":
                raise
    else:
        try:
            body = client.get(f"/stories/{ref}").json()
            return "story", str(body["id"]), str(body["human_id"])
        except ApiRequestError as exc:
            if exc.code != "not_found":
                raise
        try:
            body = client.get(f"/epics/{ref}").json()
            return "epic", str(body["id"]), str(body["human_id"])
        except ApiRequestError as exc:
            if exc.code != "not_found":
                raise
    raise ApiRequestError(
        status_code=404,
        code="not_found",
        message=f"no story or epic matches {ref!r}",
        details={"ref": ref},
    )


def audit_command(
    ref: str = typer.Argument(
        ...,
        help="Story or epic handle (KAN-123) or UUID.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit JSON output instead of a Rich table.",
    ),
) -> None:
    """
    Show the audit history for a single story or epic.
    """
    config = require_config()
    with build_client(config) as client:
        try:
            entity_type, entity_id, human_id = _resolve_entity(client, ref)
            response = client.get(f"/audit/entity/{entity_type}/{entity_id}")
        except ApiError as exc:
            exit_on_api_error(exc)
        payload: Any = response.json()

    items: list[dict[str, Any]]
    if isinstance(payload, dict) and "items" in payload:
        items = list(payload["items"])
    elif isinstance(payload, list):
        items = list(payload)
    else:
        items = []

    if as_json:
        print_json(items)
        return
    rows = [
        [
            str(item.get("occurred_at", "")),
            str(item.get("action", "")),
            f"{item.get('actor_type', '')}/{item.get('actor_id', '')}",
            str(item.get("id", "")),
        ]
        for item in items
    ]
    print_table(
        columns=["occurred_at", "action", "actor", "event_id"],
        rows=rows,
        title=f"audit trail for {human_id}",
    )
